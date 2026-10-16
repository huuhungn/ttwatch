# Ký số exe bằng SignPath Foundation (miễn phí)

> **Không bắt buộc.** Việc ký Authenticode chỉ để bớt cảnh báo SmartScreen. Không ký vẫn dùng bình thường. Bản phát hành đã có SHA256 và chứng thực nguồn gốc Sigstore (xem README); hai thứ này không cần đăng ký tài khoản nào.

Exe phát hành hiện chưa ký, nên Windows SmartScreen có thể cảnh báo. `release.yml` đã có sẵn bước ký, nhưng bước này **chỉ chạy khi** build từ tag **và** repo có biến `SIGNPATH_ORGANIZATION_ID`. Chưa cấu hình thì bản phát hành vẫn build bình thường, chưa ký.

## Điều kiện của SignPath Foundation

Theo [signpath.org/terms](https://signpath.org/terms): giấy phép được OSI công nhận (MIT đạt), nguồn công khai, dự án đã phát hành và còn được duy trì, trang chủ mô tả chức năng, không có mã độc quyền hay phần mềm không mong muốn. Đội ký phải là đội duy trì **toàn bộ** mã nguồn và script build của phần được ký. Mọi thành viên bắt buộc dùng xác thực hai lớp ở cả SignPath và GitHub.

Hãy tự đánh giá trung thực mục "toàn bộ mã nguồn là của đội": nếu còn phần mã bạn không chắc nguồn gốc hoặc quyền sử dụng, đừng nộp đơn cho tới khi xử lý xong. Thư viện bên thứ ba trong thư mục `_internal` được phép để nguyên chưa ký; ta chỉ ký `ttwatch.exe`.

## Các bước (do chủ repo thực hiện, cần tài khoản của bạn)

1. Xác thực hai lớp (2FA): kiểm tra ở <https://github.com/settings/security> với từng tài khoản thành viên, và bật *Require two-factor authentication* cho tổ chức `huuhungn` (Settings → Authentication security). API không cho biết 2FA cá nhân nên phải tự nhìn trên trang đó.
2. Nộp đơn tại <https://signpath.org/apply>. Trước đó nên có sẵn mục **Code signing policy** ở README hoặc trang tải (xem mẫu bên dưới); chỉ đưa lên khi đơn được chấp nhận để khỏi ghi sai sự thật.
3. Sau khi được duyệt, trong SignPath tạo project (slug mặc định mà workflow dùng: `ttwatch`) và signing policy `release-signing`; thêm Trusted Build System *GitHub.com* và liên kết với project; cài [SignPath GitHub App](https://github.com/apps/signpath) cho repo.
4. Trong project, tạo *Artifact configuration* mặc định:

   ```xml
   <artifact-configuration xmlns="http://signpath.io/artifact-configuration/v1">
     <zip-file>
       <pe-file path="ttwatch.exe">
         <authenticode-sign/>
       </pe-file>
     </zip-file>
   </artifact-configuration>
   ```

5. Tạo API token cho một user có quyền *submitter*. Ở GitHub (Settings → Secrets and variables → Actions):
   - secret `SIGNPATH_API_TOKEN`: token vừa tạo;
   - variable `SIGNPATH_ORGANIZATION_ID`: ID tổ chức SignPath;
   - (tuỳ chọn) variable `SIGNPATH_PROJECT_SLUG`, `SIGNPATH_POLICY_SLUG` nếu bạn đặt slug khác `ttwatch` / `release-signing`.
6. Đẩy tag `v*` như thường lệ. Workflow gửi yêu cầu ký, chờ tối đa 1 giờ để người phê duyệt bấm duyệt trong SignPath, thay `ttwatch.exe` bằng bản đã ký, kiểm tra `Get-AuthenticodeSignature` phải là `Valid`, rồi chạy thử exe và nén zip.

## Mẫu mục "Code signing policy" (đưa lên README sau khi được duyệt)

> ## Code signing policy
>
> Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).
>
> - Committers và reviewers: [anhtahaylove](https://github.com/anhtahaylove)
> - Approvers: [anhtahaylove](https://github.com/anhtahaylove)
>
> Chính sách riêng tư: chương trình này không gửi thông tin tới hệ thống mạng nào khác trừ khi người dùng yêu cầu rõ ràng (tool chỉ truy cập trang TikTok công khai bằng trình duyệt trên máy bạn).

## Lưu ý

- Chứng chỉ do SignPath Foundation cấp ghi tên SignPath Foundation làm nhà phát hành, không phải tên bạn.
- Exe vừa ký lần đầu vẫn có thể bị SmartScreen cảnh báo cho tới khi tích đủ uy tín qua lượt tải.
- Bản build chạy tay (`workflow_dispatch`) không ký; chỉ build từ tag mới ký.
