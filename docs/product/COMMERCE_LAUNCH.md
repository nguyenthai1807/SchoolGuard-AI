# LH25: từ bản pilot tới bán gói có thu tiền

Trạng thái hiện tại: **chỉ tích hợp và kiểm thử cục bộ**. `.env.example` để `LH25_PAYOS_ENABLED=false` và `LH25_REQUIRE_VERIFIED_EMAIL=false`. Không bật thu tiền trên Quick Tunnel hoặc máy cá nhân đang phục vụ nhóm thử nghiệm.

Xem thêm [cổng kiểm tra triển khai Google Cloud](GOOGLE_CLOUD_RELEASE.md). Trong
chế độ payOS, endpoint mở Pro thủ công bị khóa; tài khoản operator do Admin tạo
không tự nhận Pro. Trang `/admin` hiển thị danh sách Free/Pro, đơn hàng và các
phản hồi hung khí báo nhầm.

Cập nhật 23/10/2026: chủ dự án đã hoàn tất xác thực payOS. Dùng
`configure-commerce.ps1` để nhập riêng ba khóa của kênh thanh toán trên máy.
Khách có lịch sử đơn và nút gia hạn trong Gói của tôi. Webhook hợp lệ đồng thời
tạo hai thông báo xác nhận (email/Telegram); hàng đợi thử lại tối đa 5 lần khi
lỗi, không phụ thuộc vào trình duyệt khách. Admin xem trạng thái gửi trong
`/admin`. Những phần đã có và chưa có được ghi tại [tiến độ](IMPLEMENTATION_STATUS.md).

## Những gì đã có trong mã

- Xác minh email bằng liên kết một lần, hiệu lực 30 phút; chỉ lưu SHA-256 của mã, xác minh bằng POST. Khi bật cờ, tài khoản chưa xác minh không thể phân tích hoặc thanh toán. Đổi email sẽ xóa trạng thái xác minh cũ.
- Bộ gửi SMTP dùng TLS và URL HTTPS cố định; lỗi gửi không làm mất tài khoản, khách có thể gửi lại sau 60 giây. Chưa cấu hình dịch vụ email thì không thể bật yêu cầu xác minh khi khởi động.
- Adapter payOS tạo link checkout khi **đã bật rõ ràng**; mã đơn/số tiền do server quyết định. Link checkout và phản hồi API được kiểm tra. Webhook phải có HMAC hợp lệ, mã đơn, số tiền, tiền tệ, payment link và mã giao dịch khớp trước khi cấp Pro 30 ngày. Webhook lặp không gia hạn lần nữa. Trình duyệt quay về website **không** tự cấp quyền.
- Chế độ mặc định vẫn dùng yêu cầu Pro và xác nhận thủ công như bản pilot. Thử nghiệm tự động dùng gateway/email giả trong test; không tạo payment link thật và không gửi email thật.

## Việc chủ dự án phải chuẩn bị

1. Có tên miền riêng và nơi chạy HTTPS ổn định; không dùng URL `*.trycloudflare.com` để nhận tiền. Chuyển CSDL/video ra môi trường vận hành có sao lưu đã thử phục hồi, giám sát lỗi, giới hạn tài nguyên và quy trình cập nhật/rollback.
2. Đăng ký và xác thực tài khoản/kênh thanh toán payOS, kết nối tài khoản nhận tiền. payOS yêu cầu merchant đã xác thực trước khi dùng API. Theo [tài liệu môi trường test hiện tại của payOS](https://payos.vn/docs/moi-truong-test/), họ **không có sandbox riêng**; giao dịch thử qua API thật có thể chuyển tiền thật. Không thử khi chưa chủ động chấp thuận.
3. Xác minh miền gửi email với nhà cung cấp SMTP. Ví dụ, [Resend hỗ trợ SMTP](https://www.resend.com/changelog/smtp-service) và yêu cầu xác minh DNS cho miền gửi. Không gửi API key/mật khẩu qua chat; lưu vào secret manager của máy chủ.
4. Rà soát giấy phép Ultralytics/model/dataset dùng thương mại, đánh giá chất lượng ngã/cháy với tập kiểm thử độc lập và quy trình xử lý báo sai/bỏ sót. Soạn chính sách quyền riêng tư, điều khoản, quy trình xóa dữ liệu và yêu cầu pháp lý/thuế/hóa đơn với người có chuyên môn phù hợp. Đây chưa phải thiết bị báo cháy/y tế được chứng nhận.
5. Kiểm thử end-to-end email tới hộp thư thật, thanh toán thử **có chủ ý**, webhook hợp lệ/sai/lặp, gia hạn/hết hạn, hoàn tiền/khiếu nại, mất mạng và phục hồi sau sao lưu. Chưa có xử lý hoàn tiền tự động hay gia hạn tự trừ tiền; Pro là mua **một lần cho 30 ngày**.

## Cấu hình sau khi đã đủ điều kiện

Đặt các biến sau trong môi trường bảo mật của máy chủ (không commit `.env`):

```text
LH25_PUBLIC_BASE_URL=https://ten-mien-cua-ban.vn
LH25_REQUIRE_VERIFIED_EMAIL=true
SMTP_HOST=...
SMTP_PORT=465
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=...
LH25_PAYOS_ENABLED=true
LH25_PAYOS_CLIENT_ID=...
LH25_PAYOS_API_KEY=...
LH25_PAYOS_CHECKSUM_KEY=...
```

Đăng ký webhook payOS ở `https://ten-mien-cua-ban.vn/api/payments/payos/webhook` theo [tài liệu API payOS](https://payos.vn/docs/api/) và kiểm tra chữ ký theo [hướng dẫn payOS](https://payos.vn/docs/tich-hop-webhook/kiem-tra-du-lieu-voi-signature/). Ứng dụng sẽ từ chối khởi động chế độ xác minh email/thanh toán nếu thiếu cấu hình cơ bản hoặc URL là tunnel tạm. Việc khởi động được **không** thay thế kiểm thử và phê duyệt vận hành.
