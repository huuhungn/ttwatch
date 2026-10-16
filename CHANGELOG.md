# Lịch sử thay đổi

## Chưa phát hành

### Thêm
- Giấy phép MIT (`LICENSE`, cũng nằm trong file zip phát hành).
- Khi TikTok đòi captcha, tool tự đưa cửa sổ trình duyệt lên màn hình, báo ở khay và chờ tối đa 3 phút để bạn giải; giải xong tool tự quét tiếp rồi cất cửa sổ đi. Bỏ cuộc thì nghỉ 10 phút trước khi hiện lại.

## 0.1.0 — 2026-10-16

### Thêm
- Tab **Tổng quan**, **Cảnh báo**; ngăn chi tiết kênh với biểu đồ lịch sử và phân tích; so sánh 2–6 kênh.
- Cột xu hướng 30 ngày; chế độ xem đã lưu; bảng lệnh Ctrl+K; trợ giúp phím tắt.
- Nhập kênh từ txt/csv (kèm nhóm, ghi chú); xuất CSV lịch sử; tải bản sao lưu.
- Cảnh báo follow đổi vượt ngưỡng và video mới, kèm bóng thông báo ở khay.
- Tự cập nhật có kiểu (nhanh / quét 10 video) và giờ yên lặng.
- Trang video: thẻ tóm tắt, phân tích, đánh dấu video vượt trội, xuất CSV.
- Hoàn tác khi xóa kênh; banner khi có kênh bị dừng giữa chừng; gợi ý cách xử lý cho lỗi hay gặp.
- Giao diện sáng/tối chọn tay, bảng gọn, focus rõ, tôn trọng giảm chuyển động.
- GitHub Actions: `ci.yml` (ruff, cú pháp JS, toàn bộ test kể cả giao diện, trên Windows) và `release.yml` (build exe, chạy thử exe, nén zip + SHA256, tạo Release khi đẩy tag `v*`).
- Chip nhóm (chuột phải để đổi tên/bỏ nhóm), cột #/username dính trái, mũi tên chọn dòng, tab điều hướng bằng phím, so sánh theo % thay đổi.
- Màu chữ đạt WCAG AA ở cả hai giao diện (đo bằng test chạy trong trình duyệt).
- Tài liệu: `docs/user-guide.md`. Logo, tên và liên kết của dự án thay bằng của repo này; tên exe đổi thành `ttwatch.exe`.

### Đổi
- Schema SQLite có version (`PRAGMA user_version`) và migration theo thứ tự.
- Tự sao lưu DB mỗi ngày và trước khi migrate (giữ 7 bản).
- Kết nối SQLite đóng ngay sau khi dùng (trước đây giữ khóa file đến khi GC).
- Dữ liệu cũ mở bình thường; API cũ giữ nguyên hình dạng, chỉ thêm khóa mới.

### Sửa
- Kênh bị coi là lỗi khi TikTok chuyển trang giữa lúc đọc dữ liệu; lỗi mạng tạm thời được thử lại; số liệu ER/tăng trưởng tính cộng dồn đúng.

### Kiểm thử
- Từ 24 lên 103 test, gồm test giao diện bằng trình duyệt thật với dữ liệu giả và test hiệu năng trên 300 kênh × 200 video × 60 mốc.
