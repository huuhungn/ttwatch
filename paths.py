"""Đường dẫn dùng chung, chạy đúng cả khi chạy bằng Python lẫn khi đã đóng gói thành exe."""
import os
import sys
from pathlib import Path

APP_NAME = "Theo dõi kênh Tiktok"
FROZEN = getattr(sys, "frozen", False)
# Khi chạy bằng PyInstaller, tài nguyên (static/) được giải nén vào _MEIPASS;
# chạy bằng Python thì lấy cạnh file .py.
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
STATIC_DIR = RESOURCE_DIR / "static"


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        probe = d / ".write_test"
        probe.write_text("ok")
        probe.unlink()
        return True
    except OSError:
        return False


def _data_dir() -> Path:
    if os.environ.get("TDK_DATA_DIR"):
        d = Path(os.environ["TDK_DATA_DIR"])
        d.mkdir(parents=True, exist_ok=True)
        return d
    if not FROZEN:
        return Path(__file__).parent
    # Bản đóng gói: lưu cạnh file exe; nếu thư mục đó không ghi được thì dùng LOCALAPPDATA.
    beside_exe = Path(sys.executable).parent / "TheoDoiKenhTiktok_data"
    if _writable(beside_exe):
        return beside_exe
    fallback = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "TheoDoiKenhTiktok"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "data.db"
PROFILE_DIR = DATA_DIR / "browser_data"
