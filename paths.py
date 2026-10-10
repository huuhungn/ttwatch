"""Đường dẫn dùng chung, chạy đúng cả khi chạy bằng Python lẫn khi đã đóng gói thành exe."""
import os
import sys
from pathlib import Path

APP_NAME = "Theo dõi kênh Tiktok"
FROZEN = getattr(sys, "frozen", False)
RESOURCE_DIR = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
STATIC_DIR = RESOURCE_DIR / "static"


def _writable(d: Path) -> bool:
    try:
        d.mkdir(parents=True, exist_ok=True)
        test = d / ".write_test"
        test.write_text("ok", encoding="utf-8")
        test.unlink()
        return True
    except OSError:
        return False


def _data_dir() -> Path:
    override = os.environ.get("TDK_DATA_DIR")
    if override:
        return Path(override)
    if FROZEN:
        beside = Path(sys.executable).resolve().parent / "TheoDoiKenhTiktok_data"
        if _writable(beside):
            return beside
    local = os.environ.get("LOCALAPPDATA")
    if local:
        return Path(local) / "TheoDoiKenhTiktok"
    return Path.home() / "TheoDoiKenhTiktok"


DATA_DIR = _data_dir()
DB_PATH = DATA_DIR / "data.db"
PROFILE_DIR = DATA_DIR / "browser_data"
