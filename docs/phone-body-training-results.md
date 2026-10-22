# Kiểm tra nhận diện cơ thể sau huấn luyện

Nguồn: https://drive.google.com/drive/folders/11GtmyFtbIyrSj8snptr4I5S5WxOFCTMt

Đã hoàn tất 6 epoch trên CPU, dùng 13 clip đại diện. Train/validation/test tách theo cảnh: 114/9/9 ảnh. Nhãn train và validation chủ yếu là nhãn model tạo; nhãn người trên test đã được rà trực quan.

| Model | Đúng | Nhầm | Bỏ sót | Precision | Recall | F1 | Sai số đếm TB |
|---|---:|---:|---:|---:|---:|---:|---:|
| baseline | 39 | 5 | 2 | 88.64% | 95.12% | 91.76% | 0.78 |
| candidate | 40 | 9 | 1 | 81.63% | 97.56% | 88.89% | 0.89 |

Bài thử chỉ thấy thân người: 9 ảnh crop từ các cảnh test, tổng cộng 12 thân người được gán nhãn. Đây là phép thử giả lập, không phải video che khuất thật.

| Model | Đúng | Nhầm | Bỏ sót |
|---|---:|---:|---:|
| baseline | 8 | 0 | 4 |
| candidate | 10 | 6 | 2 |

**Quyết định: giữ YOLO11s làm mặc định.** Model vừa train bắt thêm một số người nhưng tăng nhận nhầm và làm F1 giảm ở cả hai phép thử. Không thay model đang dùng bằng một kết quả kém hơn. Checkpoint mới vẫn được lưu để nghiên cứu.

Các thay đổi đã áp dụng vào webcam: màu xanh dương cho người, cam cho vật thể; đếm cơ thể độc lập với nhận diện mặt; giữ detection yếu của người đã xác nhận khi còn khớp track và còn quan sát cơ thể thật. Không tự thêm người khi bị che kín hoàn toàn.

Giới hạn: tập test nhỏ, ngoài trời; chưa đại diện cho quán đông người. Độ trễ đo trên máy CPU đang làm việc, không phải benchmark phần cứng được kiểm soát. Cần thêm cảnh trong nhà, nhãn người bị che khuất thực và ảnh âm tính trước khi triển khai trọng số mới.

Checkpoint: `runtime/training-runs/phone-body-v2/weights/best.pt`
Báo cáo gốc: `runtime/phone-training/report.json`
Rà soát nhãn: `docs/phone-body-test-review.json`
