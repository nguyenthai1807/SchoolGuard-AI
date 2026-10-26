# Bàn giao BE-1 — Thái

## Đã triển khai

- [x] Worker YOLO/ByteTrack nhận diện người từ video local.
- [x] Vùng cấm polygon, dwell time, tâm bbox/chân người, nhiều vùng.
- [x] Một cảnh báo mỗi lượt, reset khi ra vùng hoặc mất dấu lâu.
- [x] Lưu ảnh minh chứng, sự kiện và metadata có camera/zone/run IDs.
- [x] Video chú thích H.264, chế độ không xuất video, thống kê thời gian thực thi.
- [x] Hàm callback tích hợp backend và file event để khôi phục khi giao dữ liệu lỗi.
- [x] Kiểm thử luật + pipeline video bằng detection giả lập.

## Còn phải làm với nhóm

- [ ] Minh cung cấp 3 video có quyền sử dụng: không người / đi ngoài vùng / xâm nhập.
- [ ] Thái chọn polygon đúng camera và chỉnh confidence/dwell trên video phát triển.
- [ ] Kiên/Phú xác nhận hợp đồng dữ liệu, kết nối database và giao diện.
- [ ] Chạy ≥10 kịch bản trên video kiểm thử riêng; ghi TP/FP/FN và thời gian phản hồi.
- [ ] Kiểm tra 2 camera không dùng chung tracker, reset ID khi đổi video.
- [ ] Chạy demo và quay bản dự phòng trên máy dùng báo cáo.

## Mốc BE-1 từ 15/10 tới 28/10/2026

| Ngày | Việc Thái cần thực hiện | Bằng chứng hoàn thành |
|---|---|---|
| 15–16/10 | Chạy worker, nhận video từ Minh, chốt camera/zone IDs với Kiên | video output và JSON event thật |
| 17–18/10 | Chỉnh vùng/ngưỡng, nối callback lưu Alert của Kiên | DB có Alert + ảnh của sự kiện thật |
| 19–21/10 | Ghép FE-2, đồng bộ bbox/video; xử lý lỗi tích hợp | video → AI → DB → dashboard |
| 22–24/10 | Chốt ngưỡng, chạy bộ test riêng, ghi FP/FN/tốc độ | bảng kiểm thử, cấu hình và phiên bản |
| 25–26/10 | Đóng băng tính năng, chuẩn bị sơ đồ/slide AI, quay demo | clip dự phòng + báo cáo AI |
| 27/10 | Tổng duyệt trên máy báo cáo, kiểm tra chạy offline | checklist tổng duyệt |
| 28/10 | Trình bày phần AI và hạn chế thực tế | demo và giải thích thuật toán |

## Cách trình bày phần AI

YOLO tìm bbox người; ByteTrack gắn ID theo thời gian. Điểm đại diện bbox được kiểm
tra trong polygon. Theo dõi thời gian lưu lại và phát event một lần khi đạt dwell.
Snapshot cùng tọa độ và ID camera/vùng được giao BE-2 lưu Alert và FE hiển thị.

Không báo cáo "độ chính xác 90%" từ confidence. Độ chính xác cần ground truth video
test riêng. Nêu hạn chế: ánh sáng, che khuất, ID đổi, góc camera và quy tắc polygon 2D.
Ảnh smoke test lặp hoặc bbox giả lập chỉ chứng minh pipeline chạy, không thay đánh giá
camera trường học. Realtime camera thật và phát hiện đánh nhau/đồ bỏ quên chưa triển khai.
