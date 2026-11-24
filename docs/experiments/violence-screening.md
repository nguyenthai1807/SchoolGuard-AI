# LH25 — đánh giá phát hiện xung đột (chưa phải classifier bạo lực)

## Quyết định và dữ liệu

- Hành động sản phẩm: cảnh báo **nghi chuyển động mạnh giữa người**, kèm thời điểm và bằng chứng để người dùng xác minh; không tự khẳng định có đâm/chém hoặc ai là thủ phạm.
- Sai lầm quan trọng: bỏ sót sự cố thật và báo nhầm sinh hoạt bình thường. Đo riêng recall theo đoạn sự cố, precision, cảnh báo giả/giờ và thời gian từ khởi phát tới cảnh báo; đo thêm độ trễ CPU/webcam.
- Baseline hiện tại: quy tắc pose `detect_interactions` chỉ chạy khi người dùng bật. Nó phát hiện cổ tay di chuyển nhanh gần người khác nhiều lần, không phân loại ý định hay vũ khí.
- Bản chạy của `[research] non-violent-003` (`6331f218afba4b878f686c7fb7e87af5`) **không bật** `detect_interactions`; peak 4 người, 2 khuôn mặt nhìn rõ. Replay dữ liệu pose đã lưu với quy tắc bật tạo cảnh báo lúc 2,10s và 2,37s — đây là **false positive theo nhãn clip non-violent**, không phải bằng chứng clip có bạo lực.
- Nguồn [AIRTLab](https://github.com/airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos) gắn nhãn violent/non-violent ở mức clip; nhóm non-violent cố ý có động tác nhanh dễ báo nhầm. Bản phát hành ghi mục đích nghiên cứu/giáo dục. Không dùng để huấn luyện bản thương mại nếu chưa có quyền sử dụng phù hợp.

## Thử nghiệm tiếp theo trước khi bật cảnh báo khẩn

1. Có bộ dữ liệu được phép sử dụng cho mục tiêu triển khai, gồm cả cảnh sinh hoạt nhanh, đánh nhau và sự cố có/không có vật thể nguy hiểm; gán nhãn **khoảng thời gian** của hành động, không chỉ tên clip. Không suy diễn nhãn “đâm người” từ cảnh chuyển động cổ tay.
2. Chia train/validation/test theo cảnh, diễn viên và camera; hai góc quay cùng một hành động phải ở cùng một phần chia. Giữ bộ test độc lập chưa dùng để chỉnh ngưỡng.
3. So sánh quy tắc pose hiện tại với mô hình video theo thời gian trên cùng bộ test; báo confusion matrix và các lát cắt quay lưng, che khuất, ánh sáng yếu, nhiều người, video ngắn/webcam. Đo thời gian tới cảnh báo và cảnh báo giả/giờ.
4. Chỉ nâng mức từ “nghi xung đột” lên cảnh báo khẩn sau khi định trước ngưỡng chấp nhận, đánh giá độc lập và kiểm thử thực tế có con người xác minh. Nếu không đạt, giữ tính năng thử nghiệm tắt mặc định.

Rollback: tắt `detect_interactions`; các chức năng đếm người, ngã và cháy/khói vẫn hoạt động độc lập.
