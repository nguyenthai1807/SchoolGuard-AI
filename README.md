# SchoolGuard AI

Giám sát an ninh khuôn viên trường học — MVP báo cáo ngày **28/10/2026**.

Luồng chính: video → YOLO nhận diện người → ByteTrack theo dõi → kiểm tra vùng cấm
→ ảnh minh chứng + sự kiện → backend lưu Alert → frontend hiển thị và xử lý.

## Phần BE-1 — Thái

Đã bổ sung mô-đun độc lập trong [`ai-service/`](ai-service/README.md):

- Phân tích video local bằng YOLO + ByteTrack trên CPU hoặc GPU.
- Polygon chuẩn hóa, điểm kiểm tra tâm bbox (mặc định) hoặc chân người.
- Dwell time, xử lý mất dấu ngắn, một cảnh báo cho mỗi lượt vào vùng của mỗi track.
- Ảnh JPEG minh chứng, video chú thích H.264, metadata từng khung và sự kiện JSONL.
- Làm mờ vùng người phát hiện được trước khi lưu ảnh/video (bật mặc định).
- Hợp đồng dữ liệu và hàm callback cho BE-2; test logic và pipeline không tải model.

Đọc [hướng dẫn chạy](ai-service/README.md), [hợp đồng BE-1/BE-2/FE-2](docs/AI_CONTRACT.md)
và [checklist bàn giao BE-1](docs/BE1_HANDOFF.md).
[Kết quả kiểm chứng](docs/BE1_VERIFICATION.md): 34 tests pass, YOLO thật tạo cảnh báo
trên clip mẫu và không tạo cảnh báo trên clip trống.

## Nhóm và ranh giới công việc

| Vai trò | Thành viên | Phạm vi |
|---|---|---|
| FE-1 | Khang | Đăng nhập, layout, dashboard, tích hợp frontend |
| FE-2 | Phú | Video, vùng cấm, bounding box và cảnh báo trên camera |
| FE-3 | Hân | Lịch sử, chi tiết và trạng thái cảnh báo |
| BE-1 | Thái | AI/video worker, luật vùng cấm, ảnh và metadata |
| BE-2 | Kiên | FastAPI, User/Camera/Zone/Alert, auth, DB, phân phối dữ liệu |
| TEST-1 | Bình | API/UI/end-to-end, kiểm thử hồi quy |
| TEST-2 | Minh | Video có quyền sử dụng, ground truth, đánh giá AI và demo |

Auth, cơ sở dữ liệu nghiệp vụ, WebSocket, React chưa nằm trong phần BE-1 này.
Đếm người từng khung đã có; cảnh báo đông người và vật thể bỏ quên để sau MVP.

## Quy trình đóng góp

1. Tạo nhánh `codex/<tinh-nang>` hoặc nhánh đã thống nhất với nhóm.
2. Mỗi thay đổi có mô tả, cách chạy và kết quả kiểm thử.
3. Mở pull request; nhờ người phụ trách tích hợp kiểm tra trước khi merge.
4. Không commit `.env`, trọng số YOLO, video gốc, ảnh học sinh hay thư mục `outputs/`.
