import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "packaging"
ISS = (PKG / "ttwatch.iss").read_text(encoding="utf-8-sig")
RELEASE = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
GUID = "48F3A59C-4F54-46F3-95DA-C3C43E3A4F25"


def _sections(text):
    """{section name: its lines without comments}"""
    out, current = {}, None
    for line in text.splitlines():
        m = re.match(r"\[(\w+)\]\s*$", line.strip())
        if m:
            current = out.setdefault(m.group(1), [])
        elif current is not None and line.strip() and not line.strip().startswith(";"):
            current.append(line)
    return out


class InstallerScriptTest(unittest.TestCase):
    def test_app_id_is_stable_and_shared_with_the_smoke_test(self):
        self.assertIn("AppId={{" + GUID + "}", ISS)
        smoke = (ROOT / "scripts" / "ci" / "installer_smoke.ps1").read_text(encoding="utf-8")
        self.assertIn("{" + GUID + "}", smoke)

    def test_installs_per_user_into_a_writable_folder(self):
        setup = "\n".join(_sections(ISS)["Setup"])
        self.assertIn(r"DefaultDirName={localappdata}\Programs\ttwatch", setup)
        self.assertIn("PrivilegesRequired=lowest", setup)   # the self-update must be able to replace the files

    def test_user_data_is_never_removed_or_shipped_by_the_installer(self):
        sections = _sections(ISS)
        for name in ("InstallDelete", "UninstallDelete", "Files"):
            body = "\n".join(sections[name])
            self.assertNotIn("TheoDoiKenhTiktok_data", body, name)
            self.assertNotIn("browser_data", body, name)
        self.assertEqual([l for l in sections["InstallDelete"]], [l for l in sections["InstallDelete"] if r"{app}\_internal" in l])

    def test_the_uninstaller_clears_the_start_with_windows_entry(self):
        self.assertIn('ValueName: "ttwatch"; ValueType: none; Flags: dontcreatekey uninsdeletevalue', ISS)

    def test_installer_name_matches_the_release_workflow_and_is_not_an_update_package(self):
        import updater

        self.assertIn("OutputBaseFilename=ttwatch-v{#MyAppVersion}-Setup", ISS)
        self.assertIn("ttwatch-v$ver-Setup.exe", RELEASE)
        self.assertIsNone(updater.ASSET_RE.match("ttwatch-v0.4.0-Setup.exe"))

    def test_updater_still_picks_the_zip_when_the_release_also_has_a_setup(self):
        import updater

        base = f"https://github.com/{updater.REPO}/releases/download/v0.4.0/"
        names = ["ttwatch-v0.4.0-Setup.exe", "ttwatch-v0.4.0-Setup.exe.sha256",
                 "ttwatch-v0.4.0-win64.zip", "ttwatch-v0.4.0-win64.zip.sha256"]
        payload = {"tag_name": "v0.4.0", "html_url": f"https://github.com/{updater.REPO}/releases/tag/v0.4.0",
                   "assets": [{"name": n, "browser_download_url": base + n, "size": 10} for n in names]}
        release = updater.release_from_payload(payload)
        self.assertEqual(release.zip_name, "ttwatch-v0.4.0-win64.zip")
        self.assertTrue(release.sha_url.endswith("win64.zip.sha256"))


class BuildContractTest(unittest.TestCase):
    def test_the_exe_has_its_own_icon_in_every_build_path(self):
        self.assertIn(r"--icon packaging\app.ico", (ROOT / "build.ps1").read_text(encoding="utf-8-sig"))
        self.assertIn("./build.ps1", RELEASE)   # release.yml uses build.ps1, so it cannot drift from it
        self.assertIn("SetupIconFile=app.ico", ISS)

    def test_icon_has_the_sizes_windows_asks_for(self):
        from PIL import Image

        with Image.open(PKG / "app.ico") as ico:
            sizes = ico.info["sizes"]
        for size in ((16, 16), (32, 32), (48, 48), (256, 256)):
            self.assertIn(size, sizes)

    def test_release_publishes_and_attests_the_setup_next_to_the_zip(self):
        self.assertIn("steps.installer.outputs.setup", RELEASE)
        self.assertRegex(RELEASE, r"gh release create .*\$setup .*\$setup\.sha256")
        self.assertIn("installer_smoke.ps1", RELEASE)

    def test_smoke_test_refuses_to_run_outside_ci(self):
        smoke = (ROOT / "scripts" / "ci" / "installer_smoke.ps1").read_text(encoding="utf-8")
        self.assertIn("GITHUB_ACTIONS", smoke)


@unittest.skipUnless(sys.platform == "win32", "the gate is a PowerShell script for Windows")
class CleanPackageGateTest(unittest.TestCase):
    def run_gate(self, root):
        return subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(PKG / "assert_clean_package.ps1"), "-Path", str(root)],
            capture_output=True, text=True, timeout=60)

    def package(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / "ttwatch.exe").write_bytes(b"MZ")
        (root / "_internal" / "static").mkdir(parents=True)
        (root / "_internal" / "static" / "index.html").write_text("<html>")
        return root

    def test_a_clean_package_passes(self):
        res = self.run_gate(self.package())
        self.assertEqual(res.returncode, 0, res.stderr)

    def test_a_package_without_the_exe_fails(self):
        root = self.package()
        (root / "ttwatch.exe").unlink()
        self.assertNotEqual(self.run_gate(root).returncode, 0)

    def test_user_data_in_the_package_fails_the_gate(self):
        for make in (
            lambda r: (r / "data.db").write_bytes(b"x"),
            lambda r: (r / "_internal" / "data.db-wal").write_bytes(b"x"),
            lambda r: (r / "log.txt").write_text("x"),
            lambda r: (r / "TheoDoiKenhTiktok_data").mkdir(),
            lambda r: (r / "_internal" / "static" / ".omc").mkdir(),
        ):
            root = self.package()
            make(root)
            res = self.run_gate(root)
            self.assertNotEqual(res.returncode, 0, res.stdout)
            self.assertIn("Release gate failed", res.stderr + res.stdout)


if __name__ == "__main__":
    unittest.main()
