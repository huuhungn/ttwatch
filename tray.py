"""Biểu tượng ở khay hệ thống (góc phải thanh taskbar) thay cho cửa sổ console."""
import os
import webbrowser

import pystray
from PIL import Image

from paths import APP_NAME, DATA_DIR, STATIC_DIR

GROUP_URL = "https://www.facebook.com/groups/815190970340230"
AUTHOR_URL = "https://www.facebook.com/duckuongg/"


def run_tray(url, on_quit, first_run_notice=True):
    """Chạy biểu tượng khay (chặn luồng chính cho đến khi người dùng chọn Tắt tool)."""

    def quit_(icon, _item):
        icon.visible = False
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem(f"Mở {APP_NAME}", lambda: webbrowser.open(url), default=True),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Tham gia nhóm MFG - Kiếm Tiền Tiktok Global", lambda: webbrowser.open(GROUP_URL)),
        pystray.MenuItem("Facebook tác giả", lambda: webbrowser.open(AUTHOR_URL)),
        pystray.Menu.SEPARATOR,
        pystray.MenuItem("Mở thư mục dữ liệu", lambda: os.startfile(DATA_DIR)),
        pystray.MenuItem("Tắt tool", quit_),
    )
    icon = pystray.Icon("theo_doi_kenh_tiktok", Image.open(STATIC_DIR / "logo.png"), APP_NAME, menu)

    def setup(icon):
        icon.visible = True
        if first_run_notice:
            try:
                icon.notify("Tool đang chạy ở khay hệ thống (góc phải thanh taskbar). Bấm vào biểu tượng để mở trang, chuột phải để tắt tool.",
                            APP_NAME)
            except Exception:
                pass

    icon.run(setup=setup)
