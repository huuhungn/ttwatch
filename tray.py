"""Biểu tượng ở khay hệ thống (góc phải thanh taskbar) thay cho cửa sổ console."""
import os
import webbrowser

import pystray
from PIL import Image

from paths import APP_NAME, DATA_DIR, STATIC_DIR

GROUP_URL = "https://www.facebook.com/groups/815190970340230"
AUTHOR_URL = "https://www.facebook.com/duckuongg/"


def run_tray(url: str, on_quit, first_run_notice: bool = True) -> None:
    """Chạy biểu tượng khay (chặn luồng chính cho đến khi người dùng chọn Tắt tool)."""

    def quit_(icon, _item):
        icon.stop()
        on_quit()

    menu = pystray.Menu(
        pystray.MenuItem("Mở " + APP_NAME, lambda: webbrowser.open(url)),
        pystray.MenuItem(
            "Tham gia nhóm MFG - Kiếm Tiền Tiktok Global",
            lambda: webbrowser.open(GROUP_URL),
        ),
        pystray.MenuItem("Facebook tác giả", lambda: webbrowser.open(AUTHOR_URL)),
        pystray.MenuItem("Mở thư mục dữ liệu", lambda: os.startfile(str(DATA_DIR))),
        pystray.MenuItem("Tắt tool", quit_),
    )
    image = Image.open(STATIC_DIR / "logo.png")
    icon = pystray.Icon("theo_doi_kenh_tiktok", image, APP_NAME, menu)

    def setup(icon):
        icon.visible = True
        if first_run_notice:
            icon.notify(
                "Tool đang chạy ở khay hệ thống (góc phải thanh taskbar). "
                "Bấm vào biểu tượng để mở trang, chuột phải để tắt tool."
            )

    icon.run(setup)
