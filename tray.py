"""System tray icon (right side of the taskbar) in place of a console window."""
import os
import threading
import webbrowser

import pystray
from PIL import Image

from paths import APP_NAME, DATA_DIR, STATIC_DIR

REPO_URL = "https://github.com/huuhungn/ttwatch"

_icon = None


def notify(message, title=APP_NAME):
    """Tray balloon notification (channel alerts). Silent when there is no tray: NO_TRAY runs, tests."""
    icon = _icon
    if icon is None:
        return
    try:
        icon.notify(message[:250], title)
    except Exception:
        pass


def run_tray(url, on_quit, first_run_notice=True, on_check_update=None):
    """Run the tray icon (blocks the main thread until the user picks the quit menu item)."""

    def quit_(icon, _item):
        icon.visible = False
        icon.stop()
        on_quit()

    def check_update(_icon, _item):
        # The check hits the network; keep it off the tray's own thread.
        threading.Thread(target=on_check_update, daemon=True).start()

    updates_item = [pystray.MenuItem("Kiểm tra cập nhật", check_update)] if on_check_update else []
    menu = pystray.Menu(
        pystray.MenuItem(f"Mở {APP_NAME}", lambda: webbrowser.open(url), default=True),
        pystray.Menu.SEPARATOR,
        *updates_item,
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
