# Hướng dẫn sử dụng

## Bắt đầu nhanh

1. Dán link kênh, link video hoặc `@username` vào ô trên cùng (mỗi dòng một kênh, hoặc cách nhau bằng dấu phẩy/khoảng trắng). Chọn kiểu quét rồi bấm **Thêm kênh** (hoặc Ctrl+Enter).
2. Tool lấy thông tin kênh và video bằng trình duyệt của máy bạn; tiến độ hiện ở góc trên bên phải.
3. Mỗi lần cập nhật, tool lưu một mốc lịch sử. Có từ hai mốc trở lên thì mới có mức tăng và biểu đồ.

## Các màn hình

### Kênh
Bảng chính. Chuột phải để mở menu: cập nhật nhanh, quét video theo số lượng/ngày, gắn nhóm, ghi chú, sao chép số liệu, xuất Excel, xóa.

- **Cập nhật nhanh** (F5): thông tin kênh và video mới nhất, không cuộn.
- **Quét video**: cuộn kênh để lấy nhiều video: toàn bộ, N video gần nhất, N ngày gần nhất hoặc một khoảng ngày.
- Cột **Xu hướng 30 ngày** vẽ biến động follow; bấm tiêu đề để sắp xếp theo mức tăng.
- **Chế độ xem** lưu lại ô tìm kiếm, nhóm, cột đang hiện và cách sắp xếp để gọi lại sau.
- **Xóa** kênh có 8 giây để **Hoàn tác** ngay ở thông báo; sau đó mới xóa thật cùng toàn bộ video và lịch sử.

### Tổng quan
Thẻ tổng số, biểu đồ tổng follow/view, bảng **Tăng nhanh nhất** theo 24 giờ / 7 / 30 ngày, kênh lâu chưa cập nhật (quá 3 ngày), kênh lỗi, video nổi bật 30 ngày.
Kênh mới theo dõi được đánh dấu "mới theo dõi": mức tăng của nó tính từ lần ghi nhận đầu tiên, không phải đủ cả kỳ.

### Chi tiết kênh
Chọn một kênh rồi nhấn **Space** (hoặc chuột phải → *Biểu đồ và phân tích*).

- Biểu đồ lịch sử follow, tim, view, số video theo 7/30/90 ngày hoặc tất cả.
- **View trung vị** là mức mà nửa số video vượt qua; ít bị kéo lệch bởi một video viral hơn trung bình.
- **Vượt trội**: video có view từ 2 lần trung vị trở lên (cần ít nhất 5 video).
- **Giờ đăng hiệu quả**: bản đồ nhiệt thứ × giờ, màu theo view trung bình. Khung được nêu là khung có view trung bình cao nhất trong số các khung có ít nhất 2 video.

### So sánh
Chọn 2–6 kênh (Ctrl+click), chuột phải → *So sánh các kênh đã chọn*.

### Cảnh báo
Sinh sau mỗi lần cập nhật thành công, từ lần thứ hai trở đi:
- follow đổi từ ngưỡng % trở lên (mặc định 5%, chỉnh trong **Cài đặt**; 0 = tắt);
- kênh có video mới giữa hai lần cập nhật.

Chấm đỏ ở tab cho biết số cảnh báo chưa đọc. Khay hệ thống cũng hiện bóng thông báo.

### Danh sách video
Bấm đúp một kênh (hoặc Enter). Có thẻ tóm tắt, phần **Phân tích** (đóng sẵn) tính theo đúng các video đang lọc, dấu ★ cho video vượt trội, xuất Excel hoặc CSV.

## Nhập, xuất, sao lưu

- **Nhập**: file `.txt` (mỗi dòng một kênh/link) hoặc `.csv` có dòng tiêu đề `username,group,note`. Kênh đã có không bị ghi đè nhóm khi cột nhóm để trống.
- **Xuất**: Excel danh sách kênh (25 cột), Excel/CSV video, CSV lịch sử một kênh (trong Chi tiết kênh).
- **Sao lưu**: Cài đặt → *Tải bản sao lưu* tải một bản `.db` nhất quán. Tool cũng tự sao lưu mỗi ngày và trước khi nâng cấp cấu trúc dữ liệu vào thư mục `backups/` cạnh dữ liệu (giữ 7 bản).
- **Khôi phục**: tắt tool, chép một file trong `backups/` thành `data.db` (đổi tên `data.db`, `data.db-wal`, `data.db-shm` cũ trước), mở lại.

## Phím tắt

| Phím | Việc |
|---|---|
| Ctrl+K | Bảng lệnh: tìm kênh, chuyển màn hình, chạy hành động |
| ? | Bảng phím tắt |
| Enter | Mở danh sách video |
| Space | Chi tiết kênh |
| F5 | Cập nhật nhanh |
| Del | Xóa (có hoàn tác) |
| Ctrl+A / Ctrl+C | Chọn tất cả / sao chép username |
| 1 2 3 | Kênh / Tổng quan / Cảnh báo |
| Esc | Đóng chi tiết, bỏ chọn |

## Cài đặt

- **Hiện cửa sổ trình duyệt**: bật khi TikTok hiện captcha; giải một lần, tool ghi nhớ.
- **Tự động cập nhật**: chu kỳ phút, kiểu (nhanh hoặc quét 10 video), giờ yên lặng (có thể qua nửa đêm).
- **Cảnh báo**: bật/tắt, ngưỡng follow, video mới.
- **Giao diện**: sáng/tối/theo hệ thống, bảng gọn.

## Khi gặp lỗi

| Thông báo | Cách xử lý |
|---|---|
| Cần xác minh (captcha) | Bật *Hiện cửa sổ trình duyệt*, giải captcha, quét lại. |
| Kênh không tồn tại hoặc bị khóa | Kiểm tra lại username. |
| Bị dừng giữa chừng | Tool bị tắt khi đang quét; bấm *Quét lại các kênh này* ở thanh vàng. |
| Hồ sơ trình duyệt đang bị giữ | Tắt cửa sổ trình duyệt/tool khác đang dùng cùng thư mục dữ liệu. |
| Lỗi mạng, timeout | Tool tự thử lại tối đa 3 lần; nếu vẫn lỗi hãy thử lại sau. |
