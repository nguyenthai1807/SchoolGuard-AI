# Demo trong Chrome hoặc MXterm Preview

1. Chạy `start.ps1`, mở http://127.0.0.1:8766 và đăng nhập admin bằng password trong `runtime/admin-password.txt`.
2. Vào Thư viện, tìm `01_001.avi`, chọn video. Nhấp 4 điểm khoảng `(0.01,0.08), (0.48,0.08), (0.48,0.75), (0.01,0.75)` trên ảnh rồi Lưu vùng. Đây là **vùng giả lập cho demo**, không phải ranh giới vi phạm gốc của dataset.
3. Chọn YOLO11s/640, confidence 0.35, dwell 1.5s, stride 1, clip 0 để xử lý đủ 31.83s. Bật che mờ hoặc tắt khi kiểm tra bounding box trên dữ liệu nghiên cứu.
4. Bắt đầu; quan sát tiến độ và ảnh gần nhất. Chờ Hoàn tất, phát video, nhấp các mốc sự kiện để tua. Trên lần chạy ghi nhận ngày 16/10/2026 có 4 cảnh báo, peak 3 người/frame.
5. Vào Cảnh báo, mở ảnh, tiếp nhận một cảnh báo, ghi chú và lưu. Xuất CSV; vào Hệ thống kiểm tra audit.
6. Vào Huấn luyện AI để xem số liệu từng epoch và kết quả so sánh. Nếu checkpoint không đạt điều kiện thay thế, model gốc vẫn được giữ làm mặc định; checkpoint có thể chọn riêng để so sánh.

## Các tình huống QA

- Không vẽ vùng: phát hiện người nhưng không có alert.
- Đặt vùng trên phần nền không có người: kiểm tra không tạo cảnh báo giả.
- Dwell dài hơn thời gian clip: không có alert.
- Hủy trong lúc chờ và lúc chạy: job phải chuyển cancelled, không chuyển completed.
- Upload file MP4 hỏng: trả lỗi rõ ràng.
- Viewer: xem video được, không được tạo job/duyệt cảnh báo/tạo user.
- Reload trình duyệt: còn lịch sử; restart server: còn video, cảnh báo, tài khoản và audit.

## MXterm

Mở terminal của MXterm tại thư mục repo mới, chạy `./start.ps1`, rồi nhập URL local vào Web Preview. Agent đã thử connector nhưng nhận `missing bearer token`; chưa xác nhận điều khiển tự động MXterm. Chrome đã được kiểm thử riêng.
