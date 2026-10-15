# ttwatch — theo dõi kênh TikTok, bản source để tự phát triển

Tên cũ của repo là `channel-watch`. Tên dữ liệu và biến môi trường (`TheoDoiKenhTiktok_data`, `TDK_DATA_DIR`) giữ nguyên để không mất dữ liệu đã quét.

Dựng lại từ `TheoDoiKenhTiktok.exe` (PyInstaller, Python 3.13). Đây là bản để sửa tiếp, không phải bản dịch bytecode từng dòng.

Giao diện trong `static/` lấy nguyên từ gói gốc. Phần Python viết lại theo schema, API và luồng đã đọc từ bytecode.

## Chạy

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python app.py
```

Trang mở tại `http://127.0.0.1:<cổng>/`. Dữ liệu nằm ở `TheoDoiKenhTiktok_data` cạnh file chạy, hoặc thư mục trỏ bởi `TDK_DATA_DIR`.

Tool chỉ đọc trang TikTok công khai bằng trình duyệt của máy bạn. Không gửi dữ liệu đi đâu khác. Kênh riêng tư và captcha vẫn chặn như bản gốc.

## Kiểm thử

```bash
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
TDK_DATA_DIR=$(mktemp -d) .venv/Scripts/python -m pytest -q
```

Cần đặt `TDK_DATA_DIR` sang thư mục trống: app từ chối chạy khi hai bản dùng chung một thư mục dữ liệu.
