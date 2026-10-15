# ttwatch — theo dõi kênh TikTok, bản source để tự phát triển

Tên cũ của repo là `channel-watch`. Tên dữ liệu và biến môi trường (`TheoDoiKenhTiktok_data`, `TDK_DATA_DIR`) giữ nguyên để không mất dữ liệu đã quét.

Dựng lại từ `TheoDoiKenhTiktok.exe` (PyInstaller, Python 3.13). `recovered/` là bản dựng lại từ bytecode, khớp từng code object với bản gốc và có script kiểm chứng; mã ở thư mục gốc dựng từ đó, thêm vài phần có chủ đích ghi ở `docs/scraper-diff.md`.

Giao diện trong `static/` lấy nguyên từ gói gốc.

## Chạy

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python app.py
```

Trang mở tại `http://127.0.0.1:8765/` (cổng đầu tiên còn trống trong 8765–8774). Chạy từ source thì dữ liệu nằm cạnh `app.py`; bản đóng gói thì ở `TheoDoiKenhTiktok_data` cạnh exe (hoặc `%LOCALAPPDATA%\TheoDoiKenhTiktok` nếu không ghi được). Đặt `TDK_DATA_DIR` để trỏ sang thư mục khác. `NO_OPEN=1` không mở trình duyệt, `NO_TRAY=1` không hiện biểu tượng khay.

Tool chỉ đọc trang TikTok công khai bằng trình duyệt của máy bạn. Không gửi dữ liệu đi đâu khác. Kênh riêng tư và captcha vẫn chặn như bản gốc.

## Kiểm thử

```bash
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
TDK_DATA_DIR=$(mktemp -d) .venv/Scripts/python -m pytest -q
```

Cần đặt `TDK_DATA_DIR` sang thư mục trống: app từ chối chạy khi hai bản dùng chung một thư mục dữ liệu.
