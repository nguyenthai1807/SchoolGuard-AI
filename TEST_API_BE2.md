# Kiểm tra API BE2

Script kiểm tra đăng nhập, lưu cảnh báo giả kèm ảnh, đọc lại cảnh báo, tải ảnh, cập nhật trạng thái và in thời gian phản hồi của từng request.

`/api/alerts` là luồng cảnh báo giả để kiểm tra BE2. Sự kiện AI tự phát hiện trong vùng được lưu riêng ở `/api/events` và hiển thị trong mục **Nhật ký sự kiện vùng cảnh báo** trên web.

## Chạy kiểm tra tự động

1. Mở terminal backend tại thư mục dự án và chạy:

   ```powershell
   cd "C:\Users\BACH HOA SACH\Desktop\UIT"
   python -m uvicorn main:app --reload --host 127.0.0.1 --port 8000
   ```

2. Mở terminal thứ hai, vào cùng thư mục và chạy:

   ```powershell
   python test_api_be2.py
   ```

3. Nhập tài khoản và mật khẩu. Script thử đăng nhập sai (kỳ vọng HTTP 401), đăng nhập đúng (HTTP 200 và token), rồi thực hiện phần còn lại.

Kết quả thành công sẽ có các dòng `PASS`. Thời gian từng request được in bằng mili giây. Script tạo một cảnh báo giả có `camera_id=TEST-BE2`, tải lại danh sách để xác nhận DB đã lưu, tải ảnh minh chứng và cập nhật trạng thái thành `Đang xử lý`. Bản ghi được giữ lại trong database để bạn kiểm tra trên giao diện.

## Kiểm tra thủ công qua Swagger

Mở [http://127.0.0.1:8000/docs](http://127.0.0.1:8000/docs).

1. Mở `POST /token`, chọn **Try it out**, nhập `username` và `password`, rồi chạy. Thành công là HTTP 200 có `access_token`; mật khẩu sai phải trả HTTP 401.
2. Chọn **Authorize** và đăng nhập bằng tài khoản đó (hoặc dán token nếu Swagger yêu cầu Bearer token).
3. Mở `POST /api/alerts`, nhập `camera_id` (ví dụ `TEST-BE2`), `zone_name` (ví dụ `Cổng chính`) và tải một ảnh JPEG/PNG/WebP lên. Thành công trả HTTP 201 cùng `id`.
4. Mở `GET /api/alerts` và chạy. Tìm cảnh báo vừa tạo theo `id`; response cần có `timestamp`, `location`, `zone_name`, `camera_id`, `evidence_image_url`, `image_url` và `status`.
5. Gọi `GET /api/alerts/{alert_id}/image` với ID vừa tạo để kiểm tra ảnh minh chứng.
6. Gọi `PUT /api/alerts/{alert_id}/status` với JSON `{"status":"Đang xử lý"}`, rồi đọc lại `GET /api/alerts` để xác nhận trạng thái đã đổi.

## Giải thích trường danh sách

- `timestamp`: thời gian tạo cảnh báo, trả về theo UTC (`Z`).
- `location` / `zone_name`: vị trí hoặc tên vùng.
- `camera_id`: mã camera tạo cảnh báo.
- `evidence_image_url` / `image_url`: endpoint lấy ảnh minh chứng; cần Bearer token.
- `status`: `Mới`, `Đang xử lý` hoặc `Đã xử lý`.

Các API danh sách hỗ trợ `skip`, `limit` (mặc định 100, tối đa 500) và lọc `status`. Script đo một lần cho từng request; con số này phản ánh lần chạy trên máy hiện tại, không phải benchmark tải đồng thời.

## Xem sự kiện AI tự lưu

1. Đăng nhập vào web, bật camera (hoặc tải video), khoanh vùng và chọn loại đối tượng.
2. Khi đối tượng được nhận diện trong vùng đủ thời gian cấu hình, backend lưu ảnh minh chứng và metadata sự kiện vào database.
3. Mở **Nhật ký sự kiện vùng cảnh báo** bên dưới camera, dùng ô tìm kiếm theo vị trí, loại đối tượng, `Camera trực tiếp`, tên video hoặc mã sự kiện. Danh sách tự làm mới định kỳ.
4. Có thể kiểm tra cùng dữ liệu qua `GET /api/events`; tải ảnh bằng `GET /api/events/{event_id}/image`. Xóa một sự kiện bằng `DELETE /api/events/{event_id}` (bản ghi và ảnh minh chứng sẽ bị xóa). Các endpoint cần token.
