"""Biểu tượng ở khay hệ thống (góc phải thanh taskbar) thay cho cửa sổ console."""
import os
import webbrowser

import pystray
from PIL import Image

from paths import APP_NAME, DATA_DIR, STATIC_DIR

REPO_URL = "https://github.com/huuhungn/ttwatch"

_icon = None


def notify(message, title=APP_NAME):
    """Bóng thông báo từ khay (cảnh báo kênh). Im lặng nếu chưa có khay: chạy NO_TRAY, kiểm thử."""
    icon = _icon
    if icon is None:
        return
    try:
        icon.notify(message[:250], title)
    except Exception:
        pass


def run_tray(url, on_quit, first_run_notice=True):
    """Chạy biểu tượng khay (chặn luồng chính cho đến khi người dùng chọn Tắt tool)."""

    def quit_(icon, _item):
        icon.visible = False
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem(f"Mở {APP_NAME}", lambda: webbrowser.open(url), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Mã nguồn trên GitHub", lambda: webbrowser.open(REPO_URL)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Mở thư mục dữ liệu", lambda: os.startfile(DATA_DIR)),
        pystray.MenuItem("Tắt tool", quit_),
    )
    icon = pystray.Icon("ttwatch", Image.open(STATIC_DIR / "ttwatch.png"), APP_NAME, menu)
    global _icon
    _icon = icon

    def setup(icon):
        icon.visible = True
        if first_run_notice:
            try:
                icon.notify("Tool đang chạy ở khay hệ thống (góc phải thanh taskbar). Bấm vào biểu tượng để mở trang, chuột phải để tắt tool.",
                            APP_NAME)
            except Exception:
                pass

    icon.run(setup=setup)
