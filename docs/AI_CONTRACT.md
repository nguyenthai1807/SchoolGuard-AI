# Hợp đồng đề xuất BE-1 → BE-2 / FE-2 (v1.0)

Đây là hợp đồng do BE-1 cung cấp, **chưa xác nhận với Kiên/Phú**. BE-2 quyết định endpoint,
database, auth và vận chuyển; worker không tự gọi dịch vụ ngoài hoặc cập nhật trạng thái Alert.

## Cấu hình đầu vào

`Config` nhận `camera_id`, danh sách Zone có ID và polygon chuẩn hóa, cùng ngưỡng trong
`ai-service/configs/demo.json`. Polygon theo toàn bộ khung gốc, không theo kích thước
canvas có letterbox. Một tracker mới cho mỗi lần chạy; không chia sẻ YoloDetector giữa
các luồng hoặc camera. Hỗ trợ polygon lõm, biên được tính là nằm trong vùng.

## Cảnh báo

`events.jsonl` UTF-8, mỗi dòng là một JSON độc lập:

```json
{
  "schema_version": "1.0",
  "event_id": "4a215a440a744f098b093f7a12345678",
  "run_id": "b0aa38ad51c8455aa9a8285b12345678",
  "camera_id": "CAM-01",
  "zone_id": "ZONE-01",
  "event_type": "person_in_restricted_zone",
  "severity": "high",
  "detected_at": "2026-10-15T10:00:00.000000Z",
  "video_time_seconds": 2.0,
  "frame_index": 60,
  "track_id": 7,
  "confidence": 0.91,
  "bbox": [0.6, 0.2, 0.8, 0.8],
  "anchor": "center",
  "dwell_seconds": 2.0,
  "evidence": {
    "path": "snapshots/4a215a440a744f098b093f7a12345678.jpg",
    "media_type": "image/jpeg",
    "redacted": true
  }
}
```

- `detected_at`: UTC lúc worker **tạo cảnh báo**, không phải giờ người bước vào trường
  trên một video quay sẵn. FE hiển thị múi giờ Asia/Bangkok nếu cần.
- `video_time_seconds`: thời điểm trong video, `frame_index` đánh số từ 0.
- `bbox`: [x1,y1,x2,y2] chuẩn hóa [0,1]; confidence là điểm mô hình, không phải xác suất
  một hành vi phạm quy hay độ chính xác hệ thống.
- `track_id`: chỉ có ý nghĩa trong cặp `(run_id,camera_id)`; không phải nhận diện danh tính.
- `evidence.path`: tương đối trong thư mục output của run, **không phải URL công khai**.
  BE-2 cần đọc shared disk hoặc chuyển ảnh qua endpoint upload riêng rồi trả URL có kiểm
  soát quyền. Không gửi nguyên đường dẫn máy chủ cho frontend để mong trình duyệt đọc được.
- `event_id`: BE-2 đặt unique constraint, upsert/ignore khi replay cùng event, tránh tạo
  Alert trùng. Chạy phân tích lại video sinh run/event IDs mới, không tự dedup giữa các run.
- `severity=high` chỉ là cấu hình MVP. BE-2 tạo trạng thái ban đầu `new`; bảo vệ xác minh.

## Metadata cho FE-2

`frames.jsonl` chứa `schema_version`, `run_id`, `camera_id`, `frame_index`,
`video_time_seconds`, `frame_width`, `frame_height`, `inference_ms`, `person_count`,
`zone_counts`, `event_ids` và `detections`:

```json
{
  "track_id": 7,
  "confidence": 0.91,
  "bbox": [0.6, 0.2, 0.8, 0.8],
  "label": "person",
  "zone_ids": ["ZONE-01"],
  "alerting": true
}
```

`track_id=null` khi chưa có tracking. `person_count` là số detection trong khung,
không phải số người duy nhất ra/vào. `zone_counts` có thể đếm cùng người trong hai vùng
chồng nhau. BE-2 đọc theo dòng, không tải cả file video dài vào bộ nhớ; có thể relay qua
WebSocket/polling sau khi nhóm thống nhất. Metadata chỉ cho khung đã phân tích nếu stride>1.

## Tích hợp Python trong worker BE-2

```python
from pathlib import Path
from schoolguard_ai.models import Config
from schoolguard_ai.worker import process_video

def save_alert(event: dict) -> None:
    # Kiên triển khai: validate camera/zone IDs, INSERT/upsert UNIQUE(event_id),
    # status=new, commit DB, sau đó publish notification. Giữ nguyên event_id khi retry.
    alert_repository.upsert_ai_event(event)

summary = process_video(
    Path("data/videos/cam01.mp4"),
    Config.load(Path("configs/demo.json")),
    Path("outputs"),
    event_sink=save_alert,
)
```

Đây là ví dụ adapter; `alert_repository` thuộc BE-2, không có sẵn trong mô-đun AI.
Callback được gọi sau khi ảnh và dòng event được ghi. Nếu callback lỗi, job dừng với
`failure.json`; đọc lại `events.jsonl` để retry và chỉ đánh dấu đã giao khi DB đã commit.
Callback đồng bộ; IO backend chậm làm chậm worker. Không gọi pipeline trực tiếp trong
async FastAPI request: dùng hàng đợi hoặc tiến trình job nền để API vẫn phản hồi.

Ảnh chỉ truy cập sau khi nhận event hoàn chỉnh. BE-2 phải dùng đường dẫn root/run được
tạo bởi hệ thống, không dùng `evidence.path` bất kỳ từ client mà thiếu kiểm tra path traversal.

## Cần nhóm chốt trước tích hợp

1. IDs camera/zone và ngưỡng trên từng video thực tế.
2. Cùng tiến trình/shared disk hay worker tách server; cơ chế chuyển ảnh khi tách server.
3. Enum Alert status, auth và endpoint do BE-2 cung cấp.
4. FE-2 chọn video đã chú thích hay video gốc + metadata; tránh vẽ bbox hai lần.
