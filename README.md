# ttwatch — theo dõi kênh TikTok công khai

Công cụ chạy trên máy bạn: nhập danh sách kênh TikTok, tool đọc số follow, tim, video của từng kênh, lưu lịch sử vào SQLite, vẽ biểu đồ, so sánh kênh và báo khi có thay đổi lớn. Python (FastAPI + Playwright), giao diện web local không cần npm, biểu tượng ở khay hệ thống.

Tải bản chạy sẵn cho Windows ở mục [Releases](https://github.com/huuhungn/ttwatch/releases) (giải nén rồi chạy `ttwatch.exe`). Hướng dẫn dùng: `docs/user-guide.md`; lịch sử thay đổi: `CHANGELOG.md`.

Tên dữ liệu và biến môi trường (`TheoDoiKenhTiktok_data`, `TDK_DATA_DIR`) giữ nguyên từ các bản trước để không mất dữ liệu đã quét.

## Chạy

```bash
uv venv --python 3.13 .venv
uv pip install --python .venv/Scripts/python.exe -r requirements.txt
.venv/Scripts/python -m playwright install chromium
.venv/Scripts/python app.py
```

Trang mở tại `http://127.0.0.1:8765/` (cổng đầu tiên còn trống trong 8765–8774). Chạy từ source thì dữ liệu nằm cạnh `app.py`; bản đóng gói thì ở `TheoDoiKenhTiktok_data` cạnh exe (hoặc `%LOCALAPPDATA%\TheoDoiKenhTiktok` nếu không ghi được). Đặt `TDK_DATA_DIR` để trỏ sang thư mục khác. `NO_OPEN=1` không mở trình duyệt, `NO_TRAY=1` không hiện biểu tượng khay.

Tool chỉ đọc trang TikTok công khai bằng trình duyệt của máy bạn. Không gửi dữ liệu đi đâu khác. Kênh riêng tư và captcha sẽ chặn việc đọc; tool báo lỗi chứ không cố vượt qua.

## CI và phát hành

- `.github/workflows/ci.yml`: mỗi lần push/PR chạy ruff, kiểm tra cú pháp JS và toàn bộ test (kể cả giao diện với Chrome) trên Windows.
- `.github/workflows/release.yml`: đẩy tag `v*` (ví dụ `git tag v0.1.0 && git push origin v0.1.0`) thì build exe, chạy thử exe (ping, trang chủ, tắt), nén zip kèm SHA256 và tạo GitHub Release. Chạy tay ở tab Actions thì chỉ tạo artifact.

Máy khác chỉ cần tải zip ở mục Releases, giải nén và chạy `ttwatch.exe`; dữ liệu nằm trong `TheoDoiKenhTiktok_data` cạnh exe.

## Kiểm thử

```bash
uv pip install --python .venv/Scripts/python.exe -r requirements-dev.txt
TDK_DATA_DIR=$(mktemp -d) .venv/Scripts/python -m pytest -q
.venv/Scripts/ruff check --select F,E9 .
```

Cần đặt `TDK_DATA_DIR` sang thư mục trống: app từ chối chạy khi hai bản dùng chung một thư mục dữ liệu. Test giao diện (`tests/test_ui.py`) mở trình duyệt thật (Chrome/Edge/Chromium của Playwright) với dữ liệu giả, không gọi TikTok, và tự bỏ qua nếu máy không có trình duyệt. Ảnh chụp lưu ở `docs/screens/`.

## Đóng gói exe

```powershell
powershell -File build.ps1      # tạo dist\ttwatch\ttwatch.exe (~150 MB cả thư mục)
```

Cần `uv` trong PATH; script tự cài PyInstaller vào `.venv`. `build/`, `dist/`, `*.spec` đã được ignore. Exe dùng Edge/Chrome có sẵn của máy.

## Cấu trúc

| File | Vai trò |
|---|---|
| `app.py` | FastAPI: API, trang tĩnh, xuất file, khởi động |
| `scraper.py` | Playwright, hàng đợi quét, thử lại, tự làm mới |
| `db.py` | SQLite, migration có version, sao lưu |
| `insights.py` | lịch sử, tổng quan, phân tích, so sánh, cảnh báo, chế độ xem |
| `instance_lock.py` | khóa một bản chạy trên thư mục dữ liệu |
| `tray.py`, `paths.py` | khay hệ thống, đường dẫn dữ liệu |
| `static/` | giao diện (không cần npm): `main.js` bảng kênh, `panels.js` các màn mới, `charts.js` biểu đồ SVG |
