# BE-1 — AI/video worker

Worker phân tích **file video local**, hỗ trợ 1 hoặc nhiều vùng cấm trong cùng camera.
Một lần chạy là một phiên độc lập, có tracker và thư mục kết quả riêng.

## Chạy trên Windows (PowerShell)

Từ thư mục `SchoolGuard-AI/ai-service`:

```powershell
python -m venv .venv
# Bản CPU giúp demo không phụ thuộc CUDA.
.\.venv\Scripts\python.exe -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
.\.venv\Scripts\python.exe -m schoolguard_ai --video "C:\duong-dan\video-truong-hoc.mp4" --config configs/demo.json
```

Lần đầu chạy sẽ tải trọng số `yolov8n.pt` nếu chưa có, cần mạng. Chạy thử trước ngày
báo cáo để có trọng số sẵn trên máy. Có thể đặt `model` trong config thành đường dẫn
trọng số local. Config và đường dẫn tương đối được tính từ thư mục chạy lệnh.

Trên Linux/macOS dùng `.venv/bin/python` thay cho `.venv\Scripts\python.exe`.
GPU: cài PyTorch tương thích máy rồi đặt `device` phù hợp theo tài liệu PyTorch.

## Kết quả

CLI in `output_dir`. Mở thư mục đó:

```text
outputs/<run_id>/
  config.json            cấu hình thực tế dùng để tái hiện
  events.jsonl           mỗi dòng một cảnh báo, ghi ngay sau ảnh minh chứng
  frames.jsonl           mỗi dòng một khung đã phân tích: bbox, số người, vùng
  snapshots/<event>.jpg  ảnh tại thời điểm phát cảnh báo
  annotated.mp4         H.264 để trình chiếu/web
  summary.json          số khung, số event, thời gian và tốc độ đo thực tế
```

Nếu không chuyển H.264 được, giữ `annotated.raw.mp4` và `browser_playable=false`.
Nếu phân tích lỗi, có `failure.json`, không có `summary.json` completed; các event đã
ghi vẫn giữ nguyên để BE-2 đọc lại. `--no-video` bỏ xuất video, vẫn lưu ảnh và metadata.

## Chỉnh vùng và ngưỡng

Sửa `configs/demo.json` trước khi dùng video trường học. Vùng mẫu chỉ là **nửa phải
khung hình**, không được coi là cấu hình phù hợp cho mọi camera.

| Cấu hình | Mặc định | Ý nghĩa |
|---|---|---|
| `camera_id` | CAM-01 | ID camera phải khớp BE-2 |
| `zones[].zone_id` | ZONE-01 | ID vùng khớp BE-2, duy nhất trong camera |
| `polygon` | Nửa phải | Ít nhất 3 điểm [x,y] trong [0,1], không tự cắt |
| `confidence` | 0.35 | Loại detection có điểm thấp hơn ngưỡng |
| `dwell_seconds` | 2 | Thời gian ở trong vùng trước khi cảnh báo; 0 = tức thì |
| `missing_grace_seconds` | 0.5 | Khoảng mất detection được chấp nhận |
| `anchor` | center | Tâm bbox; bottom dùng điểm giữa cạnh đáy |
| `frame_stride` | 1 | Phân tích 1/N khung; giữ thời gian theo video |
| `image_size` | 640 | Kích thước đầu vào YOLO |
| `redact_people` | true | Pixelate vùng người trên bản xuất; không thay ảnh đầu vào model |

Mất dấu ngắn được xem là cùng lượt ở trong vùng và khoảng đó tính vào dwell; đây là
heuristic. Ra khỏi vùng được quan sát thấy sẽ reset ngay. Mất dấu lâu reset lượt;
ID đổi có thể phát cảnh báo trùng người thật. Detections chưa có ID vẫn vẽ/đếm nhưng
chưa phát cảnh báo cá nhân để không gộp nhiều người vào một ID giả.

Làm mờ chỉ áp dụng người mà mô hình phát hiện được, không đảm bảo ẩn tất cả khuôn mặt.
Thời gian `video_time_seconds` dùng `frame_index / fps`, yêu cầu video tốc độ khung
hình cố định (CFR); video VFR cần chuyển CFR trước khi đánh giá. Không hỗ trợ RTSP/live
ở bản này; tốc độ xử lý nhanh/chậm không làm thay đổi thời điểm sự kiện trong video.

## Kiểm thử

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
```

Test mặc định không tải YOLO: dùng detection cố định nhưng đọc/ghi video và ảnh thật.
Nó chứng minh luật, dữ liệu và IO; **không chứng minh độ chính xác AI trên trường học**.

Smoke test dùng YOLO thật với một ảnh có người đã được phép sử dụng:

```powershell
.\.venv\Scripts\python.exe scripts/smoke_yolo.py --image "C:\duong-dan\anh-co-nguoi.jpg"
```

Script tạo clip lặp ảnh, chạy model/ByteTrack thật và kiểm tra có cảnh báo + ảnh;
sau đó chạy clip trống để kiểm tra không có người/cảnh báo.
Clip này dùng kiểm tra kỹ thuật, không phải dữ liệu đánh giá hoặc demo hành vi thực tế.

## Tích hợp

Xem [`../docs/AI_CONTRACT.md`](../docs/AI_CONTRACT.md). BE-2 cài package vào môi trường
worker, gọi `process_video(..., event_sink=...)` trong job nền và lưu Alert theo `event_id`.
FE-2 vẽ bbox và polygon theo tỉ lệ kích thước video đang hiển thị; phát video phải đồng bộ
metadata bằng `video_time_seconds`, không dùng thời điểm nhận gói.

## Nguồn kỹ thuật

API `model.track(..., persist=True, tracker="bytetrack.yaml")` và output ID dựa trên
[Ultralytics Tracking](https://docs.ultralytics.com/modes/track/).
[Predict/Results](https://docs.ultralytics.com/modes/predict/) mô tả xyxy/conf và class IDs.
