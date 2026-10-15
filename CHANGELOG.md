# Lịch sử thay đổi

## Chưa phát hành — nhánh `big-update`

### Thêm
- Tab **Tổng quan**, **Cảnh báo**; ngăn chi tiết kênh với biểu đồ lịch sử và phân tích; so sánh 2–6 kênh.
- Cột xu hướng 30 ngày; chế độ xem đã lưu; bảng lệnh Ctrl+K; trợ giúp phím tắt.
- Nhập kênh từ txt/csv (kèm nhóm, ghi chú); xuất CSV lịch sử; tải bản sao lưu.
- Cảnh báo follow đổi vượt ngưỡng và video mới, kèm bóng thông báo ở khay.
- Tự cập nhật có kiểu (nhanh / quét 10 video) và giờ yên lặng.
- Trang video: thẻ tóm tắt, phân tích, đánh dấu video vượt trội, xuất CSV.
- Hoàn tác khi xóa kênh; banner khi có kênh bị dừng giữa chừng; gợi ý cách xử lý cho lỗi hay gặp.
- Giao diện sáng/tối chọn tay, bảng gọn, focus rõ, tôn trọng giảm chuyển động.
- Tài liệu: `docs/user-guide.md`, `docs/big-update-plan.md`, `docs/overnight-log.md`.

### Đổi
- Schema SQLite có version (`PRAGMA user_version`) và migration theo thứ tự.
- Tự sao lưu DB mỗi ngày và trước khi migrate (giữ 7 bản).
- Kết nối SQLite đóng ngay sau khi dùng (trước đây giữ khóa file đến khi GC).
- Dữ liệu cũ mở bình thường; API cũ giữ nguyên hình dạng, chỉ thêm khóa mới.

### Sửa
- Toàn bộ các lệch hành vi so với bản gốc đã báo ở `docs/scraper-diff.md` (dựng lại từ bytecode).

### Kiểm thử
- Từ 24 lên 92 test, gồm test giao diện bằng trình duyệt thật với dữ liệu giả và test hiệu năng trên 300 kênh × 200 video × 60 mốc.
