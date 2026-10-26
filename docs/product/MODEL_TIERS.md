# Danh mục model LH25 (pilot)

| Gói | Checkpoint đã tích hợp | Việc thực sự làm |
|---|---|---|
| Free | `yolov8n`, `yolov8n-pose`, `yolov9t`, `yolov10n` | Phát hiện người/vật thể COCO; bản Pose tạo điểm cơ thể cho quy tắc nghi ngã |
| Pro Local | `yolo11n`, `yolo11s`, `yolo11n-pose`, `yolo12n`, `yolo26n`, `yolo26s`, `yolo26n-pose` | Thêm các checkpoint tương ứng khi file đã có; YOLO12 hiện chỉ dùng phát hiện vật thể |

Quyền được kiểm tra trên API khi tạo tác vụ, không chỉ bằng bộ chọn trên trình duyệt. Webcam và các detector lửa/khói, hung khí, khuôn mặt vẫn thuộc Pro Local theo chính sách sản phẩm. Bộ chọn chỉ mở model có file checkpoint tại máy chủ. YOLO12 là lựa chọn nghiên cứu, không phải model dùng toàn bộ tính năng; với ngã cần chọn checkpoint Pose khác.

Tên **YOLO11-Person** chỉ là cách trình bày checkpoint COCO YOLO11 để đếm người, không phải model mới được huấn luyện riêng. **YOLO26 + Fire** là hai detector phối hợp: YOLO26 phát hiện người/vật thể và `fire-smoke-v1.onnx` xử lý lửa/khói. Không đặt tên **YOLO26-Fire** như một checkpoint riêng khi chưa huấn luyện, đánh giá và lưu trọng số riêng. **YOLO12-Star** cũng chưa tồn tại dưới dạng checkpoint kết hợp. YOLOv13 có [repo nghiên cứu riêng](https://github.com/iMoonLab/yolov13), chưa nằm trong [danh mục model Ultralytics](https://docs.ultralytics.com/models); không đưa vào bộ chọn cho đến khi có adapter, checkpoint tương thích và benchmark trên CPU Windows.

Các checkpoint Free mới có thể tải lại từ `ultralytics/assets` bằng `.\.venv\Scripts\python.exe -m scripts.download_model_catalog`; script không chạy khi khởi động web. Tải trọng số không thay thế đánh giá trên video LH25 hoặc huấn luyện nhãn lửa, ngã, hung khí riêng.

Trước khi bán dịch vụ có dùng Ultralytics YOLO, cần [rà soát điều khoản AGPL-3.0/Enterprise của Ultralytics](https://www.ultralytics.com/license). Việc chia Free/Pro của LH25 là chính sách tính năng, không làm thay đổi giấy phép model/thư viện.
