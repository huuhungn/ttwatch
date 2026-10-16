import hashlib
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ["TDK_DATA_DIR"])
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import updater  # noqa: E402

CAN_RUN_SCRIPT = sys.platform == "win32" and updater._powershell() is not None


def _tmp(name):
    return Path(tempfile.mkdtemp(prefix=f"{name}-", dir=DATA))


def make_package(version="9.9.9", extra=None, exe=True, prefix="ttwatch/"):
    """A zip shaped like the release archive: one top-level folder with the exe and an _internal folder."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        if exe:
            zf.writestr(f"{prefix}ttwatch.exe", b"MZ" + b"\0" * 1_100_000)
        zf.writestr(f"{prefix}_internal/lib.dll", f"lib {version}")
        for name, data in (extra or {}).items():
            zf.writestr(name, data)
    return buf.getvalue()


class FakeGitHub:
    """A local stand-in for the GitHub API and the release download host."""

    def __init__(self):
        self.files = {}
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = outer.files.get(self.path)
                if body is None:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.server.server_port}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self):
        self.server.shutdown()
        self.server.server_close()

    def publish(self, version, package=None, *, sha=True, served=None, **payload_extra):
        """Serve a release `version`; `served` overrides the bytes actually downloaded (to fake corruption)."""
        package = package if package is not None else make_package(version)
        name = f"ttwatch-v{version}-win64.zip"
        assets = [{"name": name, "size": len(package), "browser_download_url": f"{self.base}/dl/{name}"}]
        self.files[f"/dl/{name}"] = served if served is not None else package
        if sha:
            digest = hashlib.sha256(package).hexdigest()
            assets.append({"name": f"{name}.sha256", "browser_download_url": f"{self.base}/dl/{name}.sha256"})
            self.files[f"/dl/{name}.sha256"] = f"{digest}  {name}\n".encode()
        payload = {"tag_name": f"v{version}", "html_url": f"{self.base}/release", "assets": assets, **payload_extra}
        self.files["/api"] = json.dumps(payload).encode()
        return package


class VersionTest(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(updater.parse_version("v1.2.3"), (1, 2, 3))
        self.assertEqual(updater.parse_version("0.10"), (0, 10))
        self.assertIsNone(updater.parse_version("1.2.3-beta"))
        self.assertIsNone(updater.parse_version(""))
        self.assertTrue(updater.is_newer("0.10.0", "0.9.9"))
        self.assertTrue(updater.is_newer("v1.0.1", "1.0"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0"))
        self.assertFalse(updater.is_newer("0.1.1", "0.1.2"))
        self.assertFalse(updater.is_newer("nonsense", "0.1.2"))


class ReleasePayloadTest(unittest.TestCase):
    def _payload(self, **over):
        name = "ttwatch-v0.2.0-win64.zip"
        base = updater.DOWNLOAD_PREFIX + "v0.2.0/"
        payload = {
            "tag_name": "v0.2.0",
            "html_url": f"https://github.com/{updater.REPO}/releases/tag/v0.2.0",
            "assets": [
                {"name": name, "size": 123, "browser_download_url": base + name},
                {"name": name + ".sha256", "browser_download_url": base + name + ".sha256"},
            ],
        }
        payload.update(over)
        return payload

    def test_picks_zip_and_checksum(self):
        rel = updater.release_from_payload(self._payload())
        self.assertEqual((rel.version, rel.zip_name, rel.zip_size), ("0.2.0", "ttwatch-v0.2.0-win64.zip", 123))
        self.assertTrue(rel.sha_url.endswith(".sha256"))

    def test_ignores_drafts_prereleases_and_odd_tags(self):
        self.assertIsNone(updater.release_from_payload(self._payload(draft=True)))
        self.assertIsNone(updater.release_from_payload(self._payload(prerelease=True)))
        self.assertIsNone(updater.release_from_payload(self._payload(tag_name="nightly")))
        self.assertIsNone(updater.release_from_payload(None))

    def test_asset_for_another_version_is_not_used(self):
        payload = self._payload(tag_name="v0.3.0")
        self.assertIsNone(updater.release_from_payload(payload))

    def test_refuses_downloads_from_other_hosts(self):
        payload = self._payload()
        payload["assets"][0]["browser_download_url"] = "https://evil.example/ttwatch-v0.2.0-win64.zip"
        self.assertIsNone(updater.release_from_payload(payload))

    def test_foreign_release_page_falls_back_to_the_releases_list(self):
        rel = updater.release_from_payload(self._payload(html_url="https://evil.example/x"))
        self.assertEqual(rel.page, updater.RELEASES_PAGE)

    def test_digest_field_is_used_when_there_is_no_checksum_asset(self):
        payload = self._payload()
        payload["assets"] = payload["assets"][:1]
        payload["assets"][0]["digest"] = "sha256:" + "ab" * 32
        rel = updater.release_from_payload(payload)
        self.assertIsNone(rel.sha_url)
        self.assertEqual(rel.sha_digest, "ab" * 32)


class ExtractTest(unittest.TestCase):
    def _zip(self, name, entries):
        path = _tmp(name) / "p.zip"
        with zipfile.ZipFile(path, "w") as zf:
            for n, data in entries.items():
                zf.writestr(n, data)
        return path

    def test_unpacks_and_finds_the_package_root(self):
        path = _tmp("extract-ok") / "p.zip"
        path.write_bytes(make_package())
        dest = path.parent / "out"
        updater.safe_extract(path, dest)
        root = updater.find_package_root(dest)
        self.assertEqual(root, dest / "ttwatch")
        self.assertEqual((root / "_internal" / "lib.dll").read_text(), "lib 9.9.9")

    def test_rejects_paths_that_escape_the_folder(self):
        for bad in ("../evil.txt", "ttwatch/../../evil.txt", "/abs.txt", "C:/win.txt", "ttwatch\\..\\..\\evil.txt"):
            with self.subTest(bad):
                zp = self._zip("extract-slip", {bad: "x"})
                with self.assertRaises(updater.UpdateError):
                    updater.safe_extract(zp, zp.parent / "out")
                self.assertFalse((zp.parent / "evil.txt").exists())
                self.assertFalse((zp.parent.parent / "evil.txt").exists())

    def test_package_without_the_exe_is_rejected(self):
        path = _tmp("extract-noexe") / "p.zip"
        path.write_bytes(make_package(exe=False))
        updater.safe_extract(path, path.parent / "out")
        with self.assertRaises(updater.UpdateError):
            updater.find_package_root(path.parent / "out")

    def test_not_a_zip_is_reported(self):
        path = _tmp("extract-bad") / "p.zip"
        path.write_bytes(b"this is not a zip")
        with self.assertRaises(updater.UpdateError):
            updater.safe_extract(path, path.parent / "out")


class ManagerTest(unittest.TestCase):
    def setUp(self):
        self.gh = FakeGitHub()
        self.addCleanup(self.gh.close)
        env = mock.patch.dict(os.environ, {"TTWATCH_UPDATE_API": self.gh.base + "/api"})
        env.start()
        self.addCleanup(env.stop)
        ps = mock.patch.object(updater, "_powershell", return_value="powershell.exe")
        ps.start()
        self.addCleanup(ps.stop)

    def manager(self, name, current="0.1.2", idle=True, settings=None, frozen=True):
        data, inst = _tmp(f"{name}-data"), _tmp(f"{name}-install")
        self.settings = dict(settings or {})
        self.notices, self.exited, self.prepared = [], threading.Event(), threading.Event()
        self.idle = idle
        m = updater.UpdateManager(
            get_setting=lambda k, d=None: self.settings.get(k, d),
            set_setting=self.settings.update,
            is_idle=lambda: self.idle,
            notify=self.notices.append,
            prepare_exit=self.prepared.set,
            exit_app=self.exited.set,
            current=current, frozen=frozen, data_dir=data, install_dir=inst, profile_dir=data / "browser_data")
        m.launched = []
        m._launch_helper = lambda root, rel, silent: m.launched.append((root, rel.version, silent))
        return m

    def wait_for(self, condition, timeout=20):
        end = time.time() + timeout
        while time.time() < end:
            if condition():
                return True
            time.sleep(0.02)
        return condition()

    def test_check_finds_a_newer_release(self):
        self.gh.publish("0.2.0")
        m = self.manager("check-new")
        snap = m.check()
        self.assertTrue(snap["available"])
        self.assertEqual((snap["latest"], snap["current"], snap["status"]), ("0.2.0", "0.1.2", "available"))

    def test_check_when_up_to_date_or_ahead(self):
        self.gh.publish("0.1.2")
        snap = self.manager("check-same").check()
        self.assertFalse(snap["available"])
        self.assertEqual(snap["status"], "uptodate")
        self.assertFalse(self.manager("check-ahead", current="0.3.0").check()["available"])

    def test_check_survives_network_and_garbage_errors(self):
        m = self.manager("check-offline")
        self.gh.files.clear()  # 404
        snap = m.check()
        self.assertFalse(snap["available"])
        self.assertIn("Không kiểm tra được", snap["check_error"])
        self.gh.files["/api"] = b"<html>not json"
        self.assertTrue(m.check()["check_error"])
        self.assertEqual(m.status, "idle")

    def test_install_downloads_verifies_and_hands_over(self):
        package = self.gh.publish("0.2.0")
        m = self.manager("install-ok")
        m.check()
        m.start_install()
        self.assertTrue(self.wait_for(self.exited.is_set))
        self.assertTrue(self.prepared.is_set())
        root, version, silent = m.launched[0]
        self.assertEqual((version, silent), ("0.2.0", False))
        self.assertEqual((root / "_internal" / "lib.dll").read_text(), "lib 0.2.0")
        self.assertEqual(root.parent.parent, m.install_dir / updater.UPDATE_DIR_NAME)
        self.assertFalse(list(root.parent.parent.glob("*.part")))
        self.assertTrue(package)

    def test_corrupted_download_is_rejected_and_never_installed(self):
        package = make_package()
        self.gh.publish("0.2.0", package, served=package[:-1] + b"X")
        m = self.manager("install-corrupt")
        m.check()
        m.start_install()
        self.assertTrue(self.wait_for(lambda: m.install_error))
        self.assertIn("SHA256", m.install_error)
        self.assertFalse(m.launched)
        self.assertFalse(self.exited.is_set())
        self.assertEqual(self.settings["update_failed"], "0.2.0")
        self.assertFalse(any((m.install_dir / updater.UPDATE_DIR_NAME).glob("stage-*")))

    def test_truncated_download_is_rejected(self):
        package = make_package()
        self.gh.publish("0.2.0", package, served=package[:1000])
        m = self.manager("install-short")
        m.check()
        m.start_install()
        self.assertTrue(self.wait_for(lambda: m.install_error))
        self.assertFalse(m.launched)

    def test_release_without_a_checksum_is_not_installed(self):
        self.gh.publish("0.2.0", sha=False)
        m = self.manager("install-nosha")
        m.check()
        m.start_install()
        self.assertTrue(self.wait_for(lambda: m.install_error))
        self.assertIn("SHA256", m.install_error)
        self.assertFalse(m.launched)

    def test_malicious_package_is_rejected(self):
        self.gh.publish("0.2.0", make_package(extra={"../../evil.txt": "x"}))
        m = self.manager("install-slip")
        m.check()
        m.start_install()
        self.assertTrue(self.wait_for(lambda: m.install_error))
        self.assertIn("không an toàn", m.install_error)
        self.assertFalse(m.launched)

    def test_cannot_install_from_source_or_without_a_release(self):
        self.gh.publish("0.2.0")
        m = self.manager("install-source", frozen=False)
        m.check()
        with self.assertRaises(updater.UpdateError):
            m.start_install()
        self.assertIn("mã nguồn", m.snapshot_full()["block_reason"])
        fresh = self.manager("install-none")
        with self.assertRaises(updater.UpdateError):
            fresh.start_install()

    def test_only_one_install_at_a_time(self):
        self.gh.publish("0.2.0")
        m = self.manager("install-twice")
        m.check()
        gate = threading.Event()
        original = m._stage

        def slow(rel):
            gate.wait(10)
            return original(rel)

        m._stage = slow
        m.start_install()
        with self.assertRaises(updater.UpdateError):
            m.start_install()
        gate.set()
        self.assertTrue(self.wait_for(self.exited.is_set))

    def test_auto_install_waits_for_idle_and_respects_settings(self):
        self.gh.publish("0.2.0")
        m = self.manager("auto", idle=False)
        m.checked_at = 0
        m.tick()  # checks, but a scan is running
        self.assertEqual(m.status, "available")
        self.assertFalse(m.launched)
        self.assertFalse(self.exited.is_set())
        self.idle = True
        self.settings["update_auto"] = "0"
        m.tick()
        self.assertFalse(self.exited.is_set())
        self.assertTrue(any("0.2.0" in n for n in self.notices))  # told, not installed
        self.settings["update_auto"] = "1"
        self.settings["update_skip"] = "0.2.0"
        m.tick()
        self.assertFalse(self.exited.is_set())
        del self.settings["update_skip"]
        m.tick()
        self.assertTrue(self.wait_for(self.exited.is_set))
        self.assertTrue(m.launched[0][2])  # silent: do not pop a browser window at 3 a.m.

    def test_auto_install_does_not_retry_a_version_that_failed(self):
        self.gh.publish("0.2.0")
        m = self.manager("auto-failed", settings={"update_failed": "0.2.0"})
        m.checked_at = 0
        m.tick()
        self.assertEqual(m.status, "available")
        self.assertFalse(self.exited.is_set())
        self.assertFalse(m.launched)

    def test_check_can_be_turned_off(self):
        self.gh.publish("0.2.0")
        m = self.manager("check-off", settings={"update_check": "0"})
        m.tick()
        self.assertEqual(m.status, "idle")

    def test_a_scan_that_starts_during_the_download_defers_the_install(self):
        self.gh.publish("0.2.0")
        m = self.manager("auto-defer")
        m.check()
        original = m._stage

        def stage_then_scan(rel):
            root = original(rel)
            self.idle = False  # the scheduler started a scan meanwhile
            return root

        m._stage = stage_then_scan
        m.start_install(auto=True)
        self.assertTrue(self.wait_for(lambda: m.status == "available" and not m._busy.locked()))
        self.assertFalse(m.launched)
        self.assertFalse(self.exited.is_set())
        # Back to idle: the verified copy is reused instead of downloading again.
        self.idle = True
        m._stage = original
        self.gh.files.clear()
        m.start_install(auto=True)
        self.assertTrue(self.wait_for(self.exited.is_set))
        self.assertEqual(m.launched[0][1], "0.2.0")

    def test_result_of_the_previous_update_is_read_once(self):
        data = _tmp("result-data")
        (data / updater.RESULT_NAME).write_text(json.dumps({"ok": True, "version": "0.2.0", "message": "Updated"}))
        m = updater.UpdateManager(get_setting=lambda k, d=None: d, set_setting=lambda v: None, is_idle=lambda: True,
                                  notify=self.notices.append if hasattr(self, "notices") else print,
                                  prepare_exit=lambda: None, exit_app=lambda: None,
                                  current="0.2.0", frozen=False, data_dir=data)
        self.assertEqual(m.last_result, {"ok": True, "version": "0.2.0", "message": "Updated"})
        self.assertFalse((data / updater.RESULT_NAME).exists())
        m.acknowledge()
        self.assertIsNone(m.snapshot()["last_result"])

    def test_success_result_with_an_old_running_version_is_not_reported_as_success(self):
        data = _tmp("result-stale")
        (data / updater.RESULT_NAME).write_text(json.dumps({"ok": True, "version": "0.2.0", "message": "Updated"}))
        m = updater.UpdateManager(get_setting=lambda k, d=None: d, set_setting=lambda v: None, is_idle=lambda: True,
                                  notify=print, prepare_exit=lambda: None, exit_app=lambda: None,
                                  current="0.1.2", frozen=False, data_dir=data)
        self.assertFalse(m.last_result["ok"])


@unittest.skipUnless(CAN_RUN_SCRIPT, "needs Windows PowerShell")
class ApplyScriptTest(unittest.TestCase):
    """Runs the real PowerShell script against a throwaway install folder."""

    def _install(self, name):
        base = _tmp(name)
        inst = base / "ttwatch"
        (inst / "_internal").mkdir(parents=True)
        (inst / "ttwatch.exe").write_text("OLD EXE")
        (inst / "_internal" / "shared.dll").write_text("old shared")
        (inst / "_internal" / "old_only.dll").write_text("old only")
        (inst / "keep.txt").write_text("a file the user put here")
        data = inst / "TheoDoiKenhTiktok_data"
        data.mkdir()
        (data / "data.db").write_text("PRECIOUS")
        new = inst / ".update" / "stage-9.9.9" / "ttwatch"
        (new / "_internal").mkdir(parents=True)
        (new / "ttwatch.exe").write_text("NEW EXE")
        (new / "_internal" / "shared.dll").write_text("new shared")
        (new / "_internal" / "new_only.dll").write_text("new only")
        return base, inst, new

    def _run(self, inst, new, result, *extra, pid=0):
        script = _tmp("script") / "apply.ps1"
        script.write_text(updater.APPLY_SCRIPT, encoding="utf-8-sig")
        cmd = [updater._powershell(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", str(script),
               "-ProcessId", str(pid), "-InstallDir", str(inst), "-NewDir", str(new), "-ResultFile", str(result),
               "-Version", "9.9.9", "-NoLaunch", "1", "-Retries", "3", "-RetryDelayMs", "100", "-WaitSeconds", "10", *extra]
        return subprocess.run(cmd, capture_output=True, text=True, timeout=180)

    def test_swaps_files_keeps_data_and_removes_the_old_version(self):
        base, inst, new = self._install("apply-ok")
        result = base / "result.json"
        proc = self._run(inst, new, result)
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertEqual((inst / "ttwatch.exe").read_text(), "NEW EXE")
        self.assertEqual((inst / "_internal" / "shared.dll").read_text(), "new shared")
        self.assertTrue((inst / "_internal" / "new_only.dll").exists())
        self.assertFalse((inst / "_internal" / "old_only.dll").exists())  # no stale files from the old version
        self.assertEqual((inst / "TheoDoiKenhTiktok_data" / "data.db").read_text(), "PRECIOUS")
        self.assertEqual((inst / "keep.txt").read_text(), "a file the user put here")
        self.assertFalse((inst / ".update").exists())  # no duplicate copy left behind
        self.assertEqual(json.loads(result.read_text())["ok"], True)

    def test_rolls_back_when_a_file_cannot_be_replaced(self):
        base, inst, new = self._install("apply-rollback")
        result = base / "result.json"
        # _internal is swapped first; ttwatch.exe is held open (as a running exe would be), so the second step fails.
        with open(inst / "ttwatch.exe", "rb"):
            proc = self._run(inst, new, result)
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual((inst / "ttwatch.exe").read_text(), "OLD EXE")
        self.assertEqual((inst / "_internal" / "shared.dll").read_text(), "old shared")
        self.assertTrue((inst / "_internal" / "old_only.dll").exists())
        self.assertFalse((inst / "_internal" / "new_only.dll").exists())
        self.assertEqual((inst / "TheoDoiKenhTiktok_data" / "data.db").read_text(), "PRECIOUS")
        out = json.loads(result.read_text())
        self.assertFalse(out["ok"])
        self.assertIn("Rolled back", out["message"])

    def test_waits_for_the_app_process_to_exit(self):
        base, inst, new = self._install("apply-wait")
        child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(2)"])
        started = time.time()
        proc = self._run(inst, new, base / "result.json", pid=child.pid)
        child.wait()
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        self.assertGreaterEqual(time.time() - started, 1.5)
        self.assertEqual((inst / "ttwatch.exe").read_text(), "NEW EXE")

    def test_refuses_a_package_that_contains_the_data_folder(self):
        base, inst, new = self._install("apply-protected")
        (new / "TheoDoiKenhTiktok_data").mkdir()
        (new / "TheoDoiKenhTiktok_data" / "data.db").write_text("EVIL")
        proc = self._run(inst, new, base / "result.json")
        self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
        self.assertEqual((inst / "TheoDoiKenhTiktok_data" / "data.db").read_text(), "PRECIOUS")
        self.assertEqual((inst / "ttwatch.exe").read_text(), "OLD EXE")


class ApiTest(unittest.TestCase):
    def _client(self, name, queue=0):
        import app as appmod
        from fastapi.testclient import TestClient
        from test_core import _fresh_db, _make_scraper

        db = _fresh_db(name)
        scraper = _make_scraper()
        scraper.pending = {f"k{i}": {} for i in range(queue)}
        appmod.scraper = scraper
        events = []
        appmod.updates = updater.UpdateManager(
            get_setting=db.get_setting, set_setting=db.set_settings, is_idle=lambda: not queue,
            notify=events.append, prepare_exit=lambda: None, exit_app=lambda: None,
            current="0.1.2", frozen=False, data_dir=_tmp("api-data"))
        return TestClient(appmod.app), appmod, db

    def test_ping_reports_the_version(self):
        from version import __version__
        client, *_ = self._client("upd-ping")
        self.assertEqual(client.get("/api/ping").json()["version"], __version__)

    def test_state_and_manual_check(self):
        gh = FakeGitHub()
        self.addCleanup(gh.close)
        gh.publish("0.2.0")
        client, *_ = self._client("upd-state")
        state = client.get("/api/update").json()
        self.assertEqual((state["current"], state["available"]), ("0.1.2", False))
        with mock.patch.dict(os.environ, {"TTWATCH_UPDATE_API": gh.base + "/api"}):
            state = client.post("/api/update/check").json()
        self.assertTrue(state["available"])
        self.assertFalse(state["can_install"])  # running from source
        self.assertIn("mã nguồn", state["block_reason"])
        self.assertEqual(client.post("/api/update/install", json={}).status_code, 400)

    def test_install_asks_before_interrupting_a_scan(self):
        client, appmod, _ = self._client("upd-busy", queue=2)
        r = client.post("/api/update/install", json={})
        self.assertEqual(r.status_code, 409)
        self.assertIn("quét", r.json()["detail"])
        # With force it gets past the scan check (and then stops at "nothing to install").
        self.assertEqual(client.post("/api/update/install", json={"force": True}).status_code, 400)

    def test_skip_is_remembered(self):
        client, appmod, db = self._client("upd-skip")
        client.post("/api/update/skip", json={"version": "0.2.0"})
        self.assertEqual(db.get_setting("update_skip"), "0.2.0")

    def test_manager_is_created_on_demand(self):
        client, appmod, _ = self._client("upd-lazy")
        appmod.updates = None
        state = client.get("/api/update").json()
        self.assertEqual(state["status"], "idle")
        self.assertIsNotNone(appmod.updates)
