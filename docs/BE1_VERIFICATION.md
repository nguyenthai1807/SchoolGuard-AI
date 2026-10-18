# Kết quả kiểm chứng BE-1 — 15/10/2026

## Kiểm thử tự động

- 34 tests passed với Python 3.12 trên Windows, môi trường riêng `ai-service/.venv`.
- `ruff check .`: All checks passed.
- `pip check`: No broken requirements found.
- Test video dùng OpenCV thật, detection được inject để tái hiện ngưỡng chính xác.
- Kiểm tra: không người, ngoài vùng, biên/vùng lõm, dwell, tái xâm nhập, mất dấu,
  không track ID, nhiều người/nhiều vùng, cấu hình lỗi, timestamp, video lỗi,
  snapshot, metadata, video output, làm mờ và callback lỗi giữ event cho retry.

## Smoke test YOLO thật

Dùng `bus.jpg` có sẵn trong package Ultralytics, tạo 15 khung lặp ảnh ở 10 FPS;
vùng cấm toàn khung, dwell 0.5 giây. Đây là **kiểm tra kỹ thuật**, không phải cảnh
xâm nhập thực tế, không dùng làm bảng precision/recall cho trường học.

| Phép kiểm | Kết quả |
|---|---|
| YOLOv8n + ByteTrack trên clip có người | 4 người, 4 events |
| Thời điểm phát cảnh báo đầu | 0.5 giây, frame 5 |
| Ảnh minh chứng | Ghi JPEG thành công, vùng người được pixelate |
| Video chú thích | H.264, `browser_playable=true` |
| Clip trống 10 khung | 0 người, 0 events |
| Trung bình inference clip có người | 235.693 ms/khung trên CPU máy kiểm chứng |
| FPS toàn quá trình clip có người | 2.381 FPS, gồm khởi tạo model và chuyển H.264 |

Mốc run local: `outputs/smoke/ef9685215aeb4108840f06a2632df510` (positive),
`outputs/smoke/83ce84b16d4d45dca8a1f6e9efbfc9b2` (negative).
Media và trọng số giữ ở máy kiểm chứng, được gitignore.

Phiên bản đã dùng: Ultralytics 8.4.177, torch 2.14.1+cpu, torchvision 0.29.1+cpu,
OpenCV 5.0.0.93, NumPy 2.5.2, lap 0.5.13, imageio-ffmpeg 0.6.0,
pytest 9.1.1 và ruff 0.17.0. File pyproject cho phép khoảng phiên bản; cần chốt
môi trường chạy demo của nhóm và chạy lại smoke sau khi thay dependency.

## Chưa kiểm chứng

- Độ chính xác, cảnh báo sai và bỏ sót trên video khuôn viên trường.
- Lưu Alert vào DB nghiệp vụ và hiển thị trên dashboard của nhóm.
- Latency AI → backend → frontend trên hệ thống tích hợp.
- GitHub Actions chưa coi là đã pass chỉ từ kiểm thử local; xem kết quả CI khi push.
