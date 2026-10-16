"""Self-update from GitHub Releases.

The flow: ask the GitHub API for the latest release, compare it with `version.__version__`, download the
win64 zip, check its SHA256, unpack it next to the install folder, then hand over to a small PowerShell
script. The script waits for this process to exit, swaps the program files in, deletes the old ones and
starts the new exe. If anything fails it puts the old files back, so a failed update never leaves a
half-installed app. The data folder (`TheoDoiKenhTiktok_data`) is never part of the package, so it is
never touched.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

from paths import APP_NAME, DATA_DIR, FROZEN, PROFILE_DIR
from version import __version__

REPO = "huuhungn/ttwatch"
API_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
DOWNLOAD_PREFIX = f"https://github.com/{REPO}/releases/download/"
RELEASES_PAGE = f"https://github.com/{REPO}/releases"
PACKAGE_EXE = "ttwatch.exe"
ASSET_RE = re.compile(r"^ttwatch-v(\d+(?:\.\d+){0,3})-win64\.zip$")
RESULT_NAME = "update-result.json"
UPDATE_DIR_NAME = ".update"

MAX_ZIP_BYTES = 600 * 1024 * 1024
MAX_UNPACKED_BYTES = 2 * 1024 ** 3
FIRST_CHECK_DELAY = 20     # seconds after start, so startup stays light
TICK = 60                  # seconds between background decisions
CHECK_INTERVAL = 6 * 3600  # GitHub allows 60 anonymous API calls per hour; we use ~4 per day


class UpdateError(Exception):
    """A failure whose message is fit to show to the user."""


def _override_api() -> str:
    # Test hook: lets the tests and a manual end-to-end run point the updater at a local server.
    return os.environ.get("TTWATCH_UPDATE_API", "").strip()


def api_url() -> str:
    return _override_api() or API_URL


def parse_version(text) -> tuple | None:
    """'v1.2.3' -> (1, 2, 3); anything with a suffix such as '-beta' is not a plain release -> None."""
    m = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", str(text or "").strip())
    return tuple(int(p) for p in m.group(1).split(".")) if m else None


def is_newer(candidate, current) -> bool:
    a, b = parse_version(candidate), parse_version(current)
    if a is None or b is None:
        return False
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)) > b + (0,) * (n - len(b))


def _download_allowed(url: str) -> bool:
    if url.startswith(DOWNLOAD_PREFIX):
        return True
    override = _override_api()
    if not override:
        return False
    a, b = urllib.parse.urlparse(url), urllib.parse.urlparse(override)
    return a.scheme in ("http", "https") and a.netloc == b.netloc


@dataclass
class Release:
    version: str
    tag: str
    page: str
    zip_name: str
    zip_url: str
    zip_size: int
    sha_url: str | None
    sha_digest: str | None


def release_from_payload(payload) -> Release | None:
    """Pick the win64 zip (and its checksum) out of a GitHub 'latest release' JSON; None when unusable."""
    if not isinstance(payload, dict) or payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name") or "")
    parsed = parse_version(tag)
    if parsed is None:
        return None
    assets = {a.get("name"): a for a in payload.get("assets") or [] if isinstance(a, dict)}
    for name, asset in assets.items():
        m = ASSET_RE.match(str(name))
        if not m or parse_version(m.group(1)) != parsed:
            continue
        url = str(asset.get("browser_download_url") or "")
        if not _download_allowed(url):
            return None
        sha_asset = assets.get(f"{name}.sha256")
        sha_url = str(sha_asset.get("browser_download_url") or "") if sha_asset else ""
        if sha_url and not _download_allowed(sha_url):
            sha_url = ""
        digest = str(asset.get("digest") or "")
        digest = digest[7:].lower() if digest.startswith("sha256:") else None
        page = str(payload.get("html_url") or "")
        if not page.startswith(f"https://github.com/{REPO}/") and not _override_api():
            page = RELEASES_PAGE
        return Release(".".join(str(p) for p in parsed), tag, page, str(name), url, int(asset.get("size") or 0),
                       sha_url or None, digest)
    return None


def _request(url: str):
    return urllib.request.Request(url, headers={"User-Agent": f"ttwatch/{__version__}",
                                                "Accept": "application/vnd.github+json, */*"})


def _read_small(url: str, limit: int = 1_000_000, timeout: int = 15) -> bytes:
    with urllib.request.urlopen(_request(url), timeout=timeout) as r:
        data = r.read(limit + 1)
    if len(data) > limit:
        raise UpdateError("Phản hồi từ GitHub quá lớn.")
    return data


def safe_extract(zip_path: Path, dest: Path) -> None:
    """Unpack a zip, refusing paths that would escape `dest` and archives that are absurdly large."""
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    root = dest.resolve()
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise UpdateError("File tải về không phải zip hợp lệ.") from exc
    with zf:
        infos = zf.infolist()
        if sum(i.file_size for i in infos) > MAX_UNPACKED_BYTES:
            raise UpdateError("Gói cập nhật giải nén quá lớn, bỏ qua.")
        for info in infos:
            name = info.filename.replace("\\", "/")
            parts = [p for p in name.split("/") if p not in ("", ".")]
            if name.startswith("/") or any(p == ".." or ":" in p for p in parts):
                raise UpdateError("Gói cập nhật chứa đường dẫn không an toàn.")
            if not parts:
                continue
            target = root.joinpath(*parts)
            if root not in target.resolve().parents and target.resolve() != root:
                raise UpdateError("Gói cập nhật chứa đường dẫn không an toàn.")
            if name.endswith("/") or info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as out:
                shutil.copyfileobj(src, out, 1 << 20)


def find_package_root(dest: Path) -> Path:
    """The folder inside an unpacked package that holds ttwatch.exe (the zip has one top-level folder)."""
    dest = Path(dest)
    for cand in [dest, *sorted(p for p in dest.iterdir() if p.is_dir())]:
        exe = cand / PACKAGE_EXE
        if exe.is_file() and exe.stat().st_size > 1_000_000:
            return cand
    raise UpdateError(f"Gói cập nhật không chứa {PACKAGE_EXE}.")


# Runs in a separate process (the app has to exit before its own files can be replaced). Pure ASCII on
# purpose: Windows PowerShell 5.1 reads BOM-less files in the ANSI code page.
APPLY_SCRIPT = r'''
param(
  [int]$ProcessId = 0,
  [Parameter(Mandatory = $true)][string]$InstallDir,
  [Parameter(Mandatory = $true)][string]$NewDir,
  [string]$ExeName = "ttwatch.exe",
  [Parameter(Mandatory = $true)][string]$ResultFile,
  [string]$Version = "",
  [string]$BrowserDir = "",
  [int]$Silent = 1,
  [int]$NoLaunch = 0,
  [int]$Retries = 20,
  [int]$RetryDelayMs = 1000,
  [int]$WaitSeconds = 60
)
$ErrorActionPreference = "Stop"
$protected = @("TheoDoiKenhTiktok_data", ".update")
$updateDir = Join-Path $InstallDir ".update"
$backup = Join-Path $updateDir "old"
$moved = New-Object System.Collections.ArrayList
$installed = New-Object System.Collections.ArrayList

function Write-Result([bool]$ok, [string]$message) {
  try {
    $json = [ordered]@{ ok = $ok; version = $Version; message = $message; at = (Get-Date).ToString("o") } | ConvertTo-Json -Compress
    [System.IO.File]::WriteAllText($ResultFile, $json, (New-Object System.Text.UTF8Encoding($false)))
  } catch {}
}

function Invoke-Retry([scriptblock]$action) {
  for ($i = 1; $true; $i++) {
    try { & $action; return } catch { if ($i -ge $Retries) { throw }; Start-Sleep -Milliseconds $RetryDelayMs }
  }
}

function Start-App {
  if ($NoLaunch -ne 0) { return }
  if ($Silent -ne 0) { $env:NO_OPEN = "1" }
  Start-Process -FilePath (Join-Path $InstallDir $ExeName) -WorkingDirectory $InstallDir
}

try {
  if ($ProcessId -gt 0) {
    $p = Get-Process -Id $ProcessId -ErrorAction SilentlyContinue
    if ($p) { [void]$p.WaitForExit($WaitSeconds * 1000) }
  }
  # Helpers of the old app (the Playwright node driver in the install folder, the browser using the
  # app's profile) keep files locked for a moment after the app exits; stop what is left.
  $root = (Resolve-Path -LiteralPath $InstallDir).Path.TrimEnd('\') + '\'
  $deadline = (Get-Date).AddSeconds(20)
  do {
    $left = @(Get-CimInstance Win32_Process | Where-Object {
      $_.ProcessId -ne $PID -and (
        ($_.ExecutablePath -and $_.ExecutablePath.StartsWith($root, [StringComparison]::OrdinalIgnoreCase)) -or
        ($BrowserDir -and $_.CommandLine -and $_.CommandLine.IndexOf($BrowserDir, [StringComparison]::OrdinalIgnoreCase) -ge 0))
    })
    if ($left.Count -eq 0) { break }
    foreach ($x in $left) { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue }
    Start-Sleep -Milliseconds 500
  } while ((Get-Date) -lt $deadline)

  if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force }
  New-Item -ItemType Directory -Path $backup -Force | Out-Null
  try {
    foreach ($item in @(Get-ChildItem -LiteralPath $NewDir -Force)) {
      $name = $item.Name
      if ($protected -contains $name) { throw "The package contains a protected name: $name" }
      $dst = Join-Path $InstallDir $name
      if (Test-Path -LiteralPath $dst) {
        Invoke-Retry { Move-Item -LiteralPath $dst -Destination (Join-Path $backup $name) -Force }
        [void]$moved.Add($name)
      }
      Invoke-Retry { Move-Item -LiteralPath $item.FullName -Destination $dst -Force }
      [void]$installed.Add($name)
    }
  } catch {
    $reason = $_.Exception.Message
    $restored = $true
    foreach ($name in @($moved) + @($installed) | Select-Object -Unique) {
      $dst = Join-Path $InstallDir $name
      try {
        if ($installed -contains $name -and (Test-Path -LiteralPath $dst)) {
          Invoke-Retry { Remove-Item -LiteralPath $dst -Recurse -Force }
        }
        if ($moved -contains $name) {
          Invoke-Retry { Move-Item -LiteralPath (Join-Path $backup $name) -Destination $dst -Force }
        }
      } catch { $restored = $false }
    }
    if ($restored) {
      Write-Result $false ("Rolled back: " + $reason)
      Remove-Item -LiteralPath $updateDir -Recurse -Force -ErrorAction SilentlyContinue
    } else {
      Write-Result $false ("Rollback incomplete, the previous files are in " + $backup + ": " + $reason)
    }
    Start-App
    exit 1
  }

  Write-Result $true "Updated"
  for ($i = 1; $i -le 5; $i++) {
    try { Remove-Item -LiteralPath $updateDir -Recurse -Force; break } catch { Start-Sleep -Milliseconds 500 }
  }
  Start-App
  exit 0
} catch {
  Write-Result $false ("Update failed before any file was replaced: " + $_.Exception.Message)
  Start-App
  exit 1
}
'''


def _powershell() -> str | None:
    root = os.environ.get("SystemRoot")
    if root:
        cand = Path(root) / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
        if cand.is_file():
            return str(cand)
    return shutil.which("powershell")


class UpdateManager:
    """Holds the update state, runs the checks and the install. All outside effects are injected so the
    tests can drive it without a network, a tray or a real restart."""

    def __init__(self, *, get_setting, set_setting, is_idle, notify, prepare_exit, exit_app,
                 current: str = __version__, frozen: bool = FROZEN, data_dir: Path = DATA_DIR,
                 install_dir: Path | None = None, profile_dir: Path = PROFILE_DIR):
        self.get_setting = get_setting
        self.set_setting = set_setting
        self.is_idle = is_idle
        self.notify = notify
        self.prepare_exit = prepare_exit
        self.exit_app = exit_app
        self.current = current
        self.frozen = frozen
        self.data_dir = Path(data_dir)
        self.install_dir = Path(install_dir) if install_dir else (Path(sys.executable).parent if frozen else None)
        self.profile_dir = Path(profile_dir)
        self.release: Release | None = None
        self.latest: str | None = None
        self.status = "idle"
        self.progress = 0.0
        self.check_error: str | None = None
        self.install_error: str | None = None
        self.checked_at = 0.0
        self.last_result = self._read_result()
        self._announced = self.last_result is None
        self._told = None
        self._lock = threading.Lock()
        self._busy = threading.Lock()
        self._stop = threading.Event()

    # ------------------------------------------------------------------ state

    def _read_result(self):
        path = self.data_dir / RESULT_NAME
        try:
            raw = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            return None
        try:
            path.unlink()
        except OSError:
            pass
        if not isinstance(raw, dict):
            return None
        ok = bool(raw.get("ok")) and str(raw.get("version")) == self.current
        message = str(raw.get("message") or "")
        if raw.get("ok") and not ok:
            message = "Cập nhật chưa hoàn tất: tool vẫn đang chạy bản cũ."
        return {"ok": ok, "version": str(raw.get("version") or ""), "message": message}

    def _set(self, **fields):
        with self._lock:
            for k, v in fields.items():
                setattr(self, k, v)

    def block_reason(self) -> str | None:
        """Why this copy cannot install updates by itself (None when it can)."""
        if not self.frozen:
            return "Bạn đang chạy từ mã nguồn; chỉ bản exe mới tự cập nhật."
        if sys.platform != "win32":
            return "Tự cập nhật chỉ hỗ trợ Windows."
        if self.install_dir is None or _powershell() is None:
            return "Máy không có Windows PowerShell để áp dụng bản cập nhật."
        try:
            with tempfile.TemporaryFile(dir=self.install_dir):
                pass
        except OSError:
            return f"Không có quyền ghi vào thư mục cài đặt ({self.install_dir}); hãy tải bản mới thủ công."
        return None

    def snapshot(self) -> dict:
        with self._lock:
            rel, status = self.release, self.status
            skipped = bool(rel) and self.get_setting("update_skip", "") == rel.version
            return {
                "current": self.current,
                "latest": self.latest,
                "available": rel is not None,
                "status": status,
                "progress": round(self.progress, 3),
                "check_error": self.check_error,
                "install_error": self.install_error,
                "checked_at": int(self.checked_at),
                "skipped": skipped,
                "page": rel.page if rel else RELEASES_PAGE,
                "size": rel.zip_size if rel else 0,
                "can_install": None,
                "block_reason": None,
                "last_result": self.last_result,
            }

    def snapshot_full(self) -> dict:
        snap = self.snapshot()
        reason = self.block_reason()
        snap["can_install"] = reason is None
        snap["block_reason"] = reason
        return snap

    def acknowledge(self):
        self._set(last_result=None)

    # ------------------------------------------------------------------ check

    def check(self) -> dict:
        """Ask GitHub for the latest release. Network trouble is recorded in `check_error`, not raised."""
        if self.status in ("downloading", "installing"):
            return self.snapshot()
        if not self._busy.acquire(blocking=False):
            return self.snapshot()
        try:
            previous = self.status
            self._set(status="checking")
            try:
                payload = json.loads(_read_small(api_url()))
                rel = release_from_payload(payload)
                self.checked_at = time.time()
                if rel and is_newer(rel.version, self.current):
                    self._set(release=rel, latest=rel.version, status="available", check_error=None)
                else:
                    self._set(release=None, latest=rel.version if rel else self.current, status="uptodate", check_error=None)
            except UpdateError as exc:
                self._set(status=previous if previous != "checking" else "idle", check_error=str(exc))
            except Exception as exc:
                self._set(status=previous if previous != "checking" else "idle",
                          check_error=f"Không kiểm tra được bản mới ({type(exc).__name__}). Kiểm tra kết nối mạng.")
            return self.snapshot()
        finally:
            self._busy.release()

    # ------------------------------------------------------------------ install

    def start_install(self, auto: bool = False) -> None:
        """Validate, then download and apply in a background thread. Raises UpdateError when it cannot start."""
        rel = self.release
        if rel is None:
            raise UpdateError("Chưa có bản mới để cài.")
        reason = self.block_reason()
        if reason:
            raise UpdateError(reason)
        if not self._busy.acquire(blocking=False):
            raise UpdateError("Đang bận kiểm tra hoặc cập nhật, thử lại sau giây lát.")
        self._set(status="downloading", progress=0.0, install_error=None)
        threading.Thread(target=self._install_worker, args=(rel, auto), daemon=True, name="update").start()

    def _install_worker(self, rel: Release, auto: bool) -> None:
        try:
            root = self._stage(rel)
            if auto and not self.is_idle():
                # A scan started while we were downloading: keep the staged copy and try again when idle.
                self._set(status="available")
                return
            self._set(status="installing", progress=1.0)
            self._launch_helper(root, rel, silent=auto)
        except UpdateError as exc:
            self._fail(rel, str(exc))
            return
        except Exception as exc:
            self._fail(rel, f"Lỗi không mong đợi khi cập nhật: {type(exc).__name__}: {exc}")
            return
        finally:
            self._busy.release()
        # The helper is waiting for this process to end: release the browser, then exit.
        try:
            self.prepare_exit()
        finally:
            self.exit_app()

    def _fail(self, rel: Release, message: str) -> None:
        self._set(status="available", install_error=message, progress=0.0)
        # Do not retry this version on our own; the user can still retry by hand.
        self.set_setting({"update_failed": rel.version})

    def _expected_sha(self, rel: Release) -> str:
        sha = None
        if rel.sha_url:
            text = _read_small(rel.sha_url, 4096).decode("utf-8", "replace")
            m = re.search(r"\b([0-9a-fA-F]{64})\b", text)
            sha = m.group(1).lower() if m else None
        sha = sha or rel.sha_digest
        if not sha:
            raise UpdateError("Bản phát hành không có mã SHA256 để kiểm tra, không cài tự động.")
        if rel.sha_digest and rel.sha_digest != sha:
            raise UpdateError("Mã SHA256 của bản phát hành không khớp giữa hai nguồn, không cài.")
        return sha

    def _download(self, rel: Release, dest: Path, expected_sha: str) -> None:
        h = hashlib.sha256()
        done = 0
        with urllib.request.urlopen(_request(rel.zip_url), timeout=30) as r, open(dest, "wb") as out:
            total = int(r.headers.get("Content-Length") or rel.zip_size or 0)
            if total > MAX_ZIP_BYTES:
                raise UpdateError("Gói cập nhật lớn bất thường, bỏ qua.")
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                done += len(chunk)
                if done > MAX_ZIP_BYTES:
                    raise UpdateError("Gói cập nhật lớn bất thường, bỏ qua.")
                h.update(chunk)
                out.write(chunk)
                if total:
                    self._set(progress=min(done / total, 0.99))
        if rel.zip_size and done != rel.zip_size:
            raise UpdateError("File tải về thiếu dung lượng, có thể mạng bị ngắt. Thử lại sau.")
        if h.hexdigest() != expected_sha:
            raise UpdateError("Mã SHA256 của file tải về không khớp, đã bỏ file này.")

    def _stage(self, rel: Release) -> Path:
        """Download, verify and unpack the release; return the folder to install from. Reuses a verified copy."""
        assert self.install_dir is not None  # block_reason() already ruled this out
        upd = self.install_dir / UPDATE_DIR_NAME
        stage = upd / f"stage-{rel.version}"
        if (stage / "READY").is_file():
            try:
                return find_package_root(stage)
            except UpdateError:
                pass
        for old in upd.glob("stage-*"):
            shutil.rmtree(old, ignore_errors=True)
        upd.mkdir(parents=True, exist_ok=True)
        need = max(rel.zip_size, 100 * 1024 * 1024) * 3
        if shutil.disk_usage(self.install_dir).free < need:
            raise UpdateError(f"Ổ đĩa không đủ chỗ trống (cần khoảng {need // (1024 * 1024)} MB tạm thời).")
        sha = self._expected_sha(rel)
        pkg = upd / "package.zip.part"
        try:
            self._download(rel, pkg, sha)
            safe_extract(pkg, stage)
            root = find_package_root(stage)
            (stage / "READY").write_text("ok")
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        finally:
            try:
                pkg.unlink()
            except OSError:
                pass
        return root

    def _launch_helper(self, root: Path, rel: Release, silent: bool) -> None:
        ps = _powershell()
        work = Path(tempfile.mkdtemp(prefix="ttwatch-update-"))
        script = work / "apply-update.ps1"
        script.write_text(APPLY_SCRIPT, encoding="utf-8-sig")
        cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden",
               "-File", str(script),
               "-ProcessId", str(os.getpid()), "-InstallDir", str(self.install_dir), "-NewDir", str(root),
               "-ExeName", PACKAGE_EXE, "-ResultFile", str(self.data_dir / RESULT_NAME),
               "-Version", rel.version, "-BrowserDir", str(self.profile_dir), "-Silent", "1" if silent else "0"]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        try:
            subprocess.Popen(cmd, creationflags=flags, close_fds=True, stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as exc:
            raise UpdateError(f"Không chạy được trình áp dụng bản cập nhật: {exc}") from exc

    # ------------------------------------------------------------------ background loop

    def cleanup_leftovers(self) -> None:
        if self.install_dir:
            shutil.rmtree(self.install_dir / UPDATE_DIR_NAME, ignore_errors=True)

    def _auto_install_wanted(self) -> bool:
        rel = self.release
        return bool(
            rel and self.status == "available"
            and self.get_setting("update_auto", "1") != "0"
            and self.get_setting("update_skip", "") != rel.version
            and self.get_setting("update_failed", "") != rel.version
            and self.is_idle())

    def tick(self) -> None:
        """One background decision: check when due, announce, and install when allowed."""
        if self.get_setting("update_check", "1") != "0" and time.time() - self.checked_at >= CHECK_INTERVAL:
            self.check()
        rel = self.release
        if rel and self._told != rel.version and self.get_setting("update_skip", "") != rel.version:
            # Say it once per version, and only when nothing will install it by itself.
            if self.get_setting("update_auto", "1") == "0" or self.block_reason() is not None:
                self._told = rel.version
                self.notify(f"Có bản {rel.version} mới của {APP_NAME}. Mở trang để cập nhật.")
        if not self._announced:
            self._announced = True
            if self.last_result:
                self.notify(f"Đã cập nhật lên bản {self.last_result['version']}." if self.last_result["ok"]
                            else f"Cập nhật chưa thành công: {self.last_result['message']}")
        if self.block_reason() is None and self._auto_install_wanted():
            try:
                self.start_install(auto=True)
            except UpdateError:
                pass

    def run_forever(self) -> None:
        if self._stop.wait(FIRST_CHECK_DELAY):
            return
        self.cleanup_leftovers()
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception as exc:  # never let the background thread die
                print(f"Lỗi kiểm tra cập nhật: {exc}")
            self._stop.wait(TICK)

    def start(self) -> None:
        threading.Thread(target=self.run_forever, daemon=True, name="update-check").start()

    def stop(self) -> None:
        self._stop.set()
