# LH25 — triển khai theo kế hoạch được duyệt

Ngày cập nhật: 24/10/2026. payOS đã xác thực, ngân hàng đã liên kết, kênh LH25 STORE đã tạo và đủ ba khóa đã lưu cục bộ. Gmail SMTP đã cấu hình bằng mật khẩu ứng dụng LH25 Email sau xác nhận của chủ tài khoản; đã kiểm tra TLS/đăng nhập SMTP thành công, chưa gửi email thật. Google Cloud đã có project `project-5df72dfc-5adf-4c71-997`; trang chào mừng hiển thị dùng thử đang chờ do cần trả trước hoặc khoản trả trước đang xử lý. Chưa triển khai hosting và chưa có URL HTTPS cố định. Xác minh email bắt buộc và thu tiền vẫn tắt cho tới khi có URL công khai. Chưa có giao dịch thật trong phạm vi kiểm thử.

| Hạng mục | Đã thực hiện | Còn cần thực hiện |
| --- | --- | --- |
| YOLO26 | Weights chính thức n/s/n-pose tải vào máy, tùy chọn video/webcam và kiểm tra suy luận thật | Tập kiểm thử trong nhà đủ lớn; candidate fine-tune chưa đạt gate nên không triển khai |
| Hung khí | Bảng bằng chứng, xác nhận theo thời gian, phản hồi đúng/sai, tắt mặc định | Bộ video dương/âm có nhãn hung khí độc lập; chưa chứng minh chất lượng thương mại |
| Tài khoản | Free/Pro/Admin, xác minh email tùy cấu hình, tách dữ liệu theo chủ sở hữu | PostgreSQL/migration và MFA Admin chưa triển khai; webcam cơ bản Free theo kế hoạch còn thiếu (hiện webcam thuộc Pro) |
| LH25 STORE | `/store`, đăng ký và liên kết app; `/admin` dành cho Admin | Hosting, tên miền và kiểm thử trên HTTPS công khai |
| payOS | Checkout, chữ ký webhook, mở/gia hạn Pro, chống xử lý lặp, lịch sử đơn theo khách | Khóa kênh, webhook HTTPS và kiểm thử giao dịch thật sau khi triển khai |
| Xác nhận thanh toán | Hàng đợi SQLite bền vững cho email/Telegram, ghi cùng transaction mở Pro; retry 5 lần, Admin xem trạng thái | Kiểm thử SMTP/Telegram thật; nếu máy chết ngay sau gửi và trước đánh dấu đã gửi, thông báo có thể lặp |
| Google Cloud | Tài liệu kiến trúc và kiểm tra cấu hình trên CLI/Admin | PostgreSQL, Cloud Storage, worker/hàng đợi phân tán, Edge Agent, Secret Manager, triển khai và kiểm thử phục hồi |

## Chuẩn bị webhook trước khi bật thu tiền

`python -m scripts.register_payos_webhook` chỉ kiểm tra điều kiện và hiển thị URL dự kiến. Sau khi HTTPS đã chạy, đặt `LH25_PUBLIC_BASE_URL` đúng origin rồi chạy `python -m scripts.register_payos_webhook --register` để gọi `/confirm-webhook` của payOS. Không tạo link thanh toán hay giao dịch trong bước này. Callback có chữ ký hợp lệ cho mã đơn không tồn tại được xác nhận 200 trong chế độ thiết lập; callback cho đơn đang chờ trả 503 khi xử lý thanh toán tạm dừng để provider gửi lại. Chế độ thiết lập không mở Pro.

## Cấu hình kênh payOS trên máy

Xác thực tổ chức không tự cung cấp khóa cho LH25. Theo [tài liệu payOS](https://payos.vn/docs/api/), cần tạo/chọn **kênh thanh toán** trong tài khoản đã xác thực để lấy Client ID, API key và checksum key. Không gửi khóa vào chat.

Trong thư mục dự án, chạy `./configure-commerce.ps1`. Script hỏi ba khóa bằng ô nhập ẩn, bảo toàn các dòng `.env` khác, lưu bản trước đó trong `runtime/backups/`, chưa bật thu tiền và chưa gọi API tạo giao dịch. Không đưa `.env` hoặc bản sao lưu lên Git.

Cấu hình SMTP và URL HTTPS theo [hướng dẫn thương mại](COMMERCE_LAUNCH.md). Trong môi trường cloud, dùng Secret Manager thay `.env`. Có thể kiểm tra những gì còn thiếu bằng `python -m scripts.check_release` hoặc trang `/admin`; cả hai chỉ hiển thị tình trạng, không hiển thị khóa.

## Đưa lên mạng

Chưa triển khai bản hiện tại nguyên trạng lên Cloud Run: SQLite, video và phiên camera còn ở một máy. Trước khi công khai cần hoàn thiện các adapter và migration trong [kế hoạch Google Cloud](GOOGLE_CLOUD_RELEASE.md). Chủ dự án cần tạo Cloud project, bật Billing và cung cấp **project ID**. Tên miền riêng có thể được cấu hình sau khi có môi trường staging ổn định. Không thể cam kết một URL production khi chưa tạo hạ tầng và kiểm thử dữ liệu tồn tại sau khởi động lại.
