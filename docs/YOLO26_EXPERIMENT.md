# YOLO26 trong LH25 (thử nghiệm, chưa đổi model mặc định)

Nguồn: [Ultralytics YOLO26](https://docs.ultralytics.com/vi/models/yolo26), [hướng dẫn fine-tune](https://docs.ultralytics.com/guides/finetuning-guide), [hướng dẫn Colab và video do Ultralytics dẫn](https://docs.ultralytics.com/integrations/google-colab). YOLO26n/s được huấn luyện COCO cho phát hiện người/vật thể; `yolo26n-pose` cho ước lượng khung xương. Các weights COCO **không** được huấn luyện để khẳng định có bạo lực, trộm, té ngã hay hỏa hoạn. LH25 vẫn dùng các quy tắc hoặc model riêng cho các cảnh báo đó; phải xác minh bằng chứng.

## Sử dụng trên máy đang chạy LH25

Weights chính thức đã được tải vào `models/` bằng `python -m scripts.download_yolo26`. Cần Ultralytics >=8.4.182 trong môi trường `.venv`. Khởi động lại LH25 rồi mở **Phân tích video** hoặc **Webcam trực tiếp**, chọn YOLO26n/YOLO26s hoặc YOLO26n Pose. Bật nghi té ngã/xung đột sẽ chọn model Pose cùng họ; nếu cần model hỗ trợ đếm cơ thể, hệ thống dùng YOLO26s khi có, nếu không dùng YOLO11s. YOLO11 vẫn là lựa chọn mặc định và có thể quay lại ngay.

Nếu chuyển dự án sang máy khác, weights bị Git bỏ qua: chạy `python -m scripts.download_yolo26` trong `.venv` của máy đó. Không tải checkpoints từ mirror không rõ nguồn.

## Thử fine-tune có thể tái lập

`python -m scripts.train_yolo26 --epochs 2 --batch 4 --name yolo26-person-20261023`

Script kiểm tra train/val/test tách theo cảnh, lấy pretrained `yolo26n.pt`, đóng băng một phần backbone, huấn luyện CPU và lưu checkpoint cùng provenance dưới `runtime/training-runs/<name>/`. Sau khi hoàn tất:

`python -m scripts.evaluate_yolo26 --name yolo26-person-20261023`

Đánh giá so YOLO11s với checkpoint mới trên 9 ảnh test đã được duyệt, dùng cùng ngưỡng, IoU, kích thước và CPU. Gate kỹ thuật yêu cầu F1, recall và sai số đếm không kém baseline, false positive không nhiều hơn, median latency không quá 1.5 lần. **Dù qua gate này vẫn không tự triển khai**: chỉ 9 ảnh ngoài trời/3 cảnh; nhãn train/validation phần lớn do YOLO11s sinh, dễ kế thừa lỗi. Cần tập test độc lập lớn hơn gồm webcam trong nhà, nhiều góc nhìn, che khuất, video ngã/cháy/hung khí có nhãn riêng và kiểm tra thủ công.

Lượt thử 23/10/2026 (2 epoch, CPU) **không qua gate**: YOLO11s đạt TP 36, FP 5, FN 4, F1 0,889, recall 0,90; checkpoint YOLO26n đạt TP 32, FP 2, FN 8, F1 0,865, recall 0,80. YOLO26n nhanh hơn trong phép đo nhỏ này (median 60,8 ms so với 114,3 ms) nhưng bỏ sót thêm người. Không gắn checkpoint này vào lựa chọn người dùng; các tùy chọn YOLO26 trên web dùng weights pretrained chính thức. Báo cáo chi tiết nằm trong `runtime/training-runs/yolo26-person-20261023/evaluation.json` (chỉ trên máy này).

Thử nhanh weights Pose gốc trên 3 khung của `[research] violent-005` cho số người 4, 6, 4; ở khung giữa có box trùng, không thể coi số 6 là sáu người thật. Đây là kiểm tra tương thích/sanity, **không phải** đo độ chính xác ngã hay bạo lực; cần annotation theo từng frame và video liên tục.

Giấy phép Ultralytics/weights là AGPL-3.0 hoặc Enterprise. Trước khi thương mại hóa LH25, chủ dự án phải kiểm tra nghĩa vụ AGPL và/hoặc mua giấy phép doanh nghiệp phù hợp. Việc tải weights và chạy thử cục bộ không xác nhận quyền triển khai dịch vụ đóng mã nguồn.
