"""Start with Windows: one per-user value under HKCU\\...\\Run (no admin rights, no scheduled task).

The user's choice lives in the `autostart` setting; the registry value is what Windows reads. At every
start `sync` rewrites the value when the folder was moved, so the entry never points at a dead path.
"""
import os
import sys

from paths import FROZEN

VALUE_NAME = "ttwatch"
BACKGROUND_FLAG = "--background"   # launched by Windows at logon: keep the tray, do not pop the page up
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"


class AutostartError(RuntimeError):
    """The registry refused the change; the message is shown to the user."""


def command_for(exe):
    return f'"{exe}" {BACKGROUND_FLAG}'


def should_open_browser(argv=None, env=None):
    """False for a silent start: NO_OPEN (updater restarts, tests) or the --background flag (Windows logon)."""
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if env is None else env
    return not env.get("NO_OPEN") and BACKGROUND_FLAG not in argv


class Autostart:
    def __init__(self, frozen=FROZEN, exe=None, run_key=None, approved_key=None):
        self.frozen = frozen
        self.exe = str(exe or sys.executable)
        # Tests point these at a throwaway key so the real Run entry is never touched.
        base = os.environ.get("TTWATCH_AUTOSTART_KEY")
        self.run_key = run_key or (base + r"\Run" if base else RUN_KEY)
        self.approved_key = approved_key or (base + r"\StartupApproved" if base else APPROVED_KEY)

    def unsupported_reason(self):
        if sys.platform != "win32":
            return "Chỉ có trên Windows."
        if not self.frozen:
            return "Bạn đang chạy từ mã nguồn; chỉ bản exe mới tự chạy cùng Windows."
        return None

    def command(self):
        return command_for(self.exe)

    def _read(self, key_path, name):
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path) as key:
                return winreg.QueryValueEx(key, name)[0]
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise AutostartError(f"Không đọc được cấu hình khởi động của Windows: {exc}") from exc

    def snapshot(self):
        reason = self.unsupported_reason()
        if reason:
            return {"supported": False, "reason": reason, "enabled": False, "stale": False, "blocked": False}
        registered = self._read(self.run_key, VALUE_NAME)
        approved = self._read(self.approved_key, VALUE_NAME)
        # StartupApproved\Run is what Task Manager's "Startup apps" tab writes: an odd first byte means disabled there.
        blocked = isinstance(approved, bytes) and bool(approved) and bool(approved[0] & 1)
        return {"supported": True, "reason": None, "enabled": registered is not None,
                "stale": registered is not None and registered != self.command(), "blocked": blocked}

    def enable(self, clear_block=True):
        reason = self.unsupported_reason()
        if reason:
            raise AutostartError(reason)
        import winreg
        try:
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, self.run_key, 0, winreg.KEY_SET_VALUE) as key:
                winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, self.command())
            if clear_block:   # the user just asked for it, so undo an earlier "disable" in Task Manager
                try:
                    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.approved_key, 0, winreg.KEY_SET_VALUE) as key:
                        winreg.DeleteValue(key, VALUE_NAME)
                except FileNotFoundError:
                    pass
        except OSError as exc:
            raise AutostartError(f"Không ghi được mục khởi động cùng Windows: {exc}") from exc
        return self.snapshot()

    def disable(self):
        reason = self.unsupported_reason()
        if reason:
            raise AutostartError(reason)
        import winreg
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, self.run_key, 0, winreg.KEY_SET_VALUE) as key:
                winreg.DeleteValue(key, VALUE_NAME)
        except FileNotFoundError:
            pass
        except OSError as exc:
            raise AutostartError(f"Không xóa được mục khởi động cùng Windows: {exc}") from exc
        return self.snapshot()

    def sync(self, wanted):
        """Startup check: when the user wants autostart, make sure the entry exists and points at this exe.

        A "disabled" mark from Task Manager is left alone here: that is also a choice of the user.
        """
        if not wanted or self.unsupported_reason():
            return
        state = self.snapshot()
        if not state["enabled"] or state["stale"]:
            self.enable(clear_block=False)
