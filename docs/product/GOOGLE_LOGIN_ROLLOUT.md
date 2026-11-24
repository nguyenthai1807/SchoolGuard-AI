# Bật đăng nhập Google cho LH25

Đây là cổng triển khai, không phải tính năng đã bật trên trang công khai. Không gửi client secret, ID token, mật khẩu hoặc mã OTP qua chat/Git.

1. Trong Google Cloud của nhóm, tạo OAuth **Web application** cho đúng origin HTTPS cố định sẽ phục vụ Store và LH25 cùng một máy chủ. Khi thử cục bộ, thêm `http://localhost` và `http://localhost:8770` vào Authorized JavaScript origins rồi mở LH25 bằng `http://localhost:8770` (không dùng `127.0.0.1` cho nút Google). Nếu chưa có hostname HTTPS ổn định, chỉ thử cục bộ.
2. Đặt **Client ID** (không phải client secret) vào `LH25_GOOGLE_CLIENT_ID` trong `.env`. Giữ `LH25_GOOGLE_ONLY=false`, khởi động lại và thử nút Google ở `/store` hoặc `/`.
3. Đăng nhập bằng Google của người quản trị, rồi khi phiên đó còn hiệu lực mở `/api/me/google-identity`. Lấy giá trị `subject` của chính mình và đặt vào `LH25_GOOGLE_ADMIN_SUBS` trong `.env`. Khởi động lại. Không dùng email hay tên để cấp quyền admin; backend so khớp Google subject đã xác minh.
4. Kiểm tra tài khoản quản trị vào được `/admin`, một tài khoản Google khác chỉ là khách Free và không vào `/admin`. Sau đó mới đặt `LH25_GOOGLE_ONLY=true` và khởi động lại. Chế độ này chặn đăng ký/đăng nhập mật khẩu, chặn phiên cũ chưa gắn Google và từ chối tạo tài khoản mật khẩu mới. Nếu thiếu Client ID hoặc admin subject, máy chủ từ chối khởi động để tránh tự khóa tài khoản.
5. Tài khoản cũ có email giống Google **không tự nối** với Google: nối tự động theo email có thể chiếm tài khoản. Cần luồng xác minh/chuyển đổi riêng trước khi bỏ đăng nhập cũ cho khách đã có dữ liệu.

Trước khi mở bán, thử lại đăng nhập Google trong trình duyệt thật trên hostname production, thanh toán payOS, email xác minh, Telegram từng khách và quyền xem dữ liệu. Firebase Store tĩnh hiện chỉ giới thiệu, không có backend đăng nhập/thanh toán; không bật Google-only trên một bản static rồi gọi đó là dịch vụ đang chạy.
