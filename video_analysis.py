"""Video object tracking and clothing-color grouping for the SchoolGuard demo."""

import os
from collections import defaultdict
from io import BytesIO
from pathlib import Path
from threading import Lock
from time import monotonic

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError

PERSON_CLASS = 0
VEHICLE_CLASSES = {
    1: "Xe đạp",
    2: "Ô tô",
    3: "Xe máy",
    5: "Xe buýt",
    7: "Xe tải",
}
TRACK_CLASSES = [PERSON_CLASS, *VEHICLE_CLASSES.keys()]
CLASS_LABELS = {
    0: "Người",
    1: "Xe đạp",
    2: "Ô tô",
    3: "Xe máy",
    5: "Xe buýt",
    7: "Xe tải",
}
CLASS_COLORS = {
    0: "#2563EB",
    1: "#06B6D4",
    2: "#DC2626",
    3: "#EA580C",
    5: "#9333EA",
    7: "#CA8A04",
}
GROUP_DISTANCE_THRESHOLD = float(os.getenv("UNIFORM_SIMILARITY_THRESHOLD", "0.34"))
_live_models = {}
_live_model_seen = {}
_live_model_lock = Lock()
_live_presence = {}
_live_presence_lock = Lock()
MAX_LIVE_STREAMS = 4


def _inside_zone(box, zone):
    x1, y1, x2, y2 = box
    anchor = os.getenv("ZONE_ANCHOR", "bottom").lower()
    px = (x1 + x2) / 2
    py = y2 if anchor == "bottom" else (y1 + y2) / 2
    return zone["x"] <= px <= zone["x"] + zone["width"] and zone["y"] <= py <= zone["y"] + zone["height"]


def _get_model():
    """Create an isolated tracker for each uploaded video analysis."""
    from ultralytics import YOLO

    return YOLO(os.getenv("YOLO_MODEL", "yolo11n.pt"))


def _get_live_model(stream_id):
    if stream_id not in _live_models:
        from ultralytics import YOLO

        if len(_live_models) >= MAX_LIVE_STREAMS:
            oldest = min(_live_model_seen, key=_live_model_seen.get)
            _live_models.pop(oldest, None)
            _live_model_seen.pop(oldest, None)
        _live_models[stream_id] = YOLO(os.getenv("YOLO_MODEL", "yolo11n.pt"))
    _live_model_seen[stream_id] = monotonic()
    return _live_models[stream_id]


def release_live_stream(stream_id: str) -> bool:
    """Release tracker and dwell state when a browser stream stops."""
    with _live_model_lock:
        removed = _live_models.pop(stream_id, None) is not None
        _live_model_seen.pop(stream_id, None)
    with _live_presence_lock:
        for key in [key for key in _live_presence if key[0] == stream_id]:
            _live_presence.pop(key, None)
    return removed


def _validate_encoded_image_dimensions(image_bytes: bytes) -> None:
    """Read only the image header before OpenCV allocates the decoded frame."""
    try:
        with Image.open(BytesIO(image_bytes)) as image:
            width, height = image.size
    except (Image.DecompressionBombError, UnidentifiedImageError, OSError) as error:
        raise ValueError("Không đọc được thông tin khung hình camera.") from error
    if width <= 0 or height <= 0 or width > 1920 or height > 1080:
        raise ValueError("Khung hình camera tối đa Full HD (1920×1080).")


def detect_live_frame_jpeg(jpeg_bytes: bytes, zones=None, stream_id="default", selected_classes=None) -> dict:
    """Detect people and common vehicles in one browser webcam frame."""
    _validate_encoded_image_dimensions(jpeg_bytes)
    frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        raise ValueError("Không giải mã được khung hình camera.")
    if frame.shape[1] > 1920 or frame.shape[0] > 1080:
        raise ValueError("Khung hình camera tối đa Full HD (1920×1080).")

    class_source = TRACK_CLASSES if selected_classes is None else selected_classes
    classes = [int(value) for value in class_source if int(value) in TRACK_CLASSES]
    with _live_model_lock:
        result = _get_live_model(stream_id).track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=classes,
            conf=0.3,
            verbose=False,
        )[0]
        active_streams = set(_live_models)
    detections = []
    boxes = result.boxes
    if boxes is not None:
        coordinates = boxes.xyxy.cpu().numpy()
        class_ids = boxes.cls.int().cpu().tolist()
        confidences = boxes.conf.cpu().tolist()
        track_ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(class_ids)
        for box, class_id, confidence, track_id in zip(coordinates, class_ids, confidences, track_ids):
            detections.append(
                {
                    "label": CLASS_LABELS.get(class_id, "Khác"),
                    "confidence": round(float(confidence), 3),
                    "box": [round(float(value), 1) for value in box],
                    "color": CLASS_COLORS.get(class_id, "#64748B"),
                    "class_id": int(class_id),
                    "track_id": int(track_id) if track_id is not None else None,
                }
            )
    now = monotonic()
    dwell_target = max(0.0, float(os.getenv("ZONE_DWELL_SECONDS", "5")))
    loss_grace = max(0.0, float(os.getenv("TRACK_MISSING_GRACE_SECONDS", "0.5")))
    events = []
    observed = set()
    with _live_presence_lock:
        for old_key in list(_live_presence):
            if old_key[0] not in active_streams:
                _live_presence.pop(old_key, None)
        for detection in detections:
            if detection["track_id"] is None:
                continue
            x1, y1, x2, y2 = detection["box"]
            normalized_box = [x1 / frame.shape[1], y1 / frame.shape[0], x2 / frame.shape[1], y2 / frame.shape[0]]
            for zone in zones or []:
                if detection["class_id"] not in zone.get("classes", TRACK_CLASSES) or not _inside_zone(normalized_box, zone):
                    continue
                key = (stream_id, zone["id"], detection["track_id"], detection["class_id"])
                observed.add(key)
                presence = _live_presence.get(key)
                center = ((x1 + x2) / (2 * frame.shape[1]), (y1 + y2) / (2 * frame.shape[0]))
                if presence is not None and now - presence.get("last_seen", now) > loss_grace:
                    presence = {"started": now, "triggered": False}
                    _live_presence[key] = presence
                if presence is None:
                    # If ByteTrack assigns a fresh ID after a brief dropout, reconnect a nearby
                    # same-class track in the same zone for at most one second.
                    candidate_key = None
                    candidate_distance = 0.12
                    for old_key, old_state in _live_presence.items():
                        if (
                            old_key in observed
                            or old_key[0] != stream_id
                            or old_key[1] != zone["id"]
                            or old_key[3] != detection["class_id"]
                        ):
                            continue
                        if now - old_state.get("last_seen", now) > loss_grace:
                            continue
                        old_center = old_state.get("center")
                        if old_center is None:
                            continue
                        distance = ((old_center[0] - center[0]) ** 2 + (old_center[1] - center[1]) ** 2) ** 0.5
                        if distance < candidate_distance:
                            candidate_key, candidate_distance = old_key, distance
                    if candidate_key is not None:
                        presence = _live_presence.pop(candidate_key)
                    else:
                        presence = {"started": now, "triggered": False}
                    _live_presence[key] = presence
                presence["last_seen"] = now
                presence["center"] = center
                dwell = now - presence["started"]
                if dwell >= dwell_target and not presence["triggered"]:
                    presence["triggered"] = True
                    events.append({"zone_id": zone["id"], "zone_name": zone.get("name", "Vùng"), "object_type": detection["label"], "track_id": detection["track_id"], "dwell_seconds": round(dwell, 1)})
        for key in list(_live_presence):
            if key[0] == stream_id and key not in observed and now - _live_presence[key].get("last_seen", now) > loss_grace:
                _live_presence.pop(key, None)
    return {"width": int(frame.shape[1]), "height": int(frame.shape[0]), "detections": detections, "events": events}


def annotate_live_event_jpeg(jpeg_bytes: bytes, event: dict, detections: list, zones: list) -> bytes:
    frame = cv2.imdecode(np.frombuffer(jpeg_bytes, dtype=np.uint8), cv2.IMREAD_COLOR)
    if frame is None:
        return jpeg_bytes
    zone = next((item for item in zones if item["id"] == event["zone_id"]), None)
    if zone:
        height, width = frame.shape[:2]
        x, y = int(zone["x"] * width), int(zone["y"] * height)
        cv2.rectangle(frame, (x, y), (x + int(zone["width"] * width), y + int(zone["height"] * height)), (20, 184, 166), 3)
        cv2.putText(frame, zone.get("name", "Vùng"), (x, max(22, y - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (20, 184, 166), 2)
    target = next((item for item in detections if item.get("track_id") == event.get("track_id")), None)
    if target:
        x1, y1, x2, y2 = (int(value) for value in target["box"])
        cv2.rectangle(frame, (x1, y1), (x2, y2), (37, 99, 235), 3)
        cv2.putText(frame, f"{event['object_type']} ID {event.get('track_id')}", (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (37, 99, 235), 2)
    ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return encoded.tobytes() if ok else jpeg_bytes


def _shirt_histogram(frame: np.ndarray, xyxy: np.ndarray) -> np.ndarray | None:
    height, width = frame.shape[:2]
    x1, y1, x2, y2 = (int(value) for value in xyxy)
    box_width, box_height = x2 - x1, y2 - y1
    if box_width < 20 or box_height < 45:
        return None

    # Use the upper torso and avoid most of the head and the outer box background.
    left = max(0, x1 + int(box_width * 0.20))
    right = min(width, x2 - int(box_width * 0.20))
    top = max(0, y1 + int(box_height * 0.28))
    bottom = min(height, y1 + int(box_height * 0.67))
    crop = frame[top:bottom, left:right]
    if crop.size == 0:
        return None
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV)
    hist = cv2.calcHist([hsv], [0, 1], None, [12, 4], [0, 180, 0, 256])
    cv2.normalize(hist, hist, alpha=1, norm_type=cv2.NORM_L1)
    return hist


def _group_for_histogram(hist: np.ndarray, groups: dict[str, dict]) -> str:
    closest_group = None
    closest_distance = 1.0
    for group_name, group in groups.items():
        distance = cv2.compareHist(hist, group["histogram"], cv2.HISTCMP_BHATTACHARYYA)
        if distance < closest_distance:
            closest_distance = distance
            closest_group = group_name

    if closest_group is None or closest_distance > GROUP_DISTANCE_THRESHOLD:
        group_name = f"Đồng phục {len(groups) + 1}"
        groups[group_name] = {"histogram": hist.copy(), "track_ids": set()}
        return group_name
    return closest_group


def analyze_video(input_path: str, output_path: str, zones=None) -> dict:
    """Track people and common vehicles, then group person tracks by shirt-color similarity."""
    capture = cv2.VideoCapture(input_path)
    if not capture.isOpened():
        raise ValueError("Không mở được video. Hãy dùng MP4, MOV, AVI, MKV hoặc WebM.")

    fps = capture.get(cv2.CAP_PROP_FPS)
    fps = fps if 1 <= fps <= 120 else 25.0
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    expected_frames = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    if width <= 0 or height <= 0 or expected_frames <= 0:
        capture.release()
        raise ValueError("Không đọc được thông tin khung hình của video.")
    if expected_frames / fps > 180:
        capture.release()
        raise ValueError("Video demo tối đa 3 phút để tránh xử lý quá lâu.")

    output_path_obj = Path(output_path)
    writer = cv2.VideoWriter(
        str(output_path_obj), cv2.VideoWriter_fourcc(*"VP80"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError("Không khởi tạo được bộ ghi video MP4.")

    seen_tracks = {class_id: set() for class_id in TRACK_CLASSES}
    vehicle_counts = defaultdict(set)
    groups: dict[str, dict] = {}
    track_groups: dict[int, str] = {}
    processed_frames = 0
    hard_frame_cap = int(min(max(fps, 30.0), 60.0) * 180)
    dwell_target = max(0.0, float(os.getenv("ZONE_DWELL_SECONDS", "5")))
    loss_grace = max(0.0, float(os.getenv("TRACK_MISSING_GRACE_SECONDS", "0.5")))
    zone_events = []
    presence = {}
    visual_alert_until = {}

    try:
        model = _get_model()
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            if processed_frames >= hard_frame_cap:
                raise ValueError("Video vượt quá giới hạn xử lý cứng 3 phút/60 FPS.")
            results = model.track(
                frame,
                persist=True,
                tracker="bytetrack.yaml",
                classes=TRACK_CLASSES,
                verbose=False,
            )
            result = results[0]
            annotated = result.plot()
            media_time = processed_frames / fps
            for zone in zones or []:
                zx, zy = int(zone["x"] * width), int(zone["y"] * height)
                zw, zh = int(zone["width"] * width), int(zone["height"] * height)
                zone_alerted = any(key[0] == zone["id"] and until >= media_time for key, until in visual_alert_until.items())
                zone_color = (0, 0, 230) if zone_alerted else (20, 184, 166)
                cv2.rectangle(annotated, (zx, zy), (zx + zw, zy + zh), zone_color, 4 if zone_alerted else 2)
                cv2.putText(annotated, zone.get("name", "Vùng"), (zx, max(18, zy - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, zone_color, 2)
            boxes = result.boxes
            if boxes is not None and len(boxes) > 0:
                xyxy = boxes.xyxy.cpu().numpy()
                class_ids = boxes.cls.int().cpu().tolist()
                track_ids = boxes.id.int().cpu().tolist() if boxes.id is not None else [None] * len(class_ids)
                for coordinates, class_id, track_id in zip(xyxy, class_ids, track_ids):
                    if track_id is None:
                        continue
                    track_id = int(track_id)
                    normalized = [coordinates[0] / width, coordinates[1] / height, coordinates[2] / width, coordinates[3] / height]
                    for zone in zones or []:
                        key = (zone["id"], track_id, class_id)
                        if class_id in zone.get("classes", TRACK_CLASSES) and _inside_zone(normalized, zone):
                            state = presence.setdefault(key, {"started": media_time, "triggered": False, "last_seen": media_time})
                            state["last_seen"] = media_time
                            if visual_alert_until.get((zone["id"], track_id), -1) >= media_time:
                                x1, y1, x2, y2 = (int(value) for value in coordinates)
                                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 230), 4)
                                cv2.putText(annotated, f"CANH BAO ID {track_id}", (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 230), 2)
                            if media_time - state["started"] >= dwell_target and not state["triggered"]:
                                state["triggered"] = True
                                visual_alert_until[(zone["id"], track_id)] = media_time + 5.0
                                x1, y1, x2, y2 = (int(value) for value in coordinates)
                                zx, zy = int(zone["x"] * width), int(zone["y"] * height)
                                zw, zh = int(zone["width"] * width), int(zone["height"] * height)
                                cv2.rectangle(annotated, (zx, zy), (zx + zw, zy + zh), (0, 0, 230), 4)
                                cv2.rectangle(annotated, (x1, y1), (x2, y2), (0, 0, 230), 4)
                                cv2.putText(annotated, f"CANH BAO {CLASS_LABELS.get(class_id, 'Khac')} ID {track_id}", (x1, max(22, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 0, 230), 2)
                                event_name = f"event_{len(zone_events) + 1}.jpg"
                                event_path = str(Path(output_path).with_name(Path(output_path).stem + "_" + event_name))
                                cv2.imwrite(event_path, annotated)
                                zone_events.append({"zone_id": zone["id"], "zone_name": zone.get("name", "Vùng"), "object_type": CLASS_LABELS.get(class_id, "Khác"), "track_id": track_id, "media_offset_seconds": round(media_time, 2), "image_path": event_path})
                        else:
                            presence.pop(key, None)
                    seen_tracks[class_id].add(track_id)
                    if class_id in VEHICLE_CLASSES:
                        vehicle_counts[VEHICLE_CLASSES[class_id]].add(track_id)
                        continue

                    hist = _shirt_histogram(frame, coordinates)
                    if hist is None:
                        continue
                    if track_id not in track_groups:
                        track_groups[track_id] = _group_for_histogram(hist, groups)
                    group_name = track_groups[track_id]
                    group = groups[group_name]
                    group["track_ids"].add(track_id)
                    # Smooth lighting changes over time for this group's clothing reference.
                    cv2.accumulateWeighted(hist, group["histogram"], 0.08)

                    x1, y1 = int(coordinates[0]), int(coordinates[1])
                    cv2.putText(
                        annotated,
                        f"ID {track_id} | {group_name}",
                        (max(0, x1), max(20, y1 - 8)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.55,
                        (255, 255, 0),
                        2,
                        cv2.LINE_AA,
                    )
            for key in list(presence):
                if media_time - presence[key].get("last_seen", media_time) > loss_grace:
                    presence.pop(key, None)
            writer.write(annotated)
            processed_frames += 1
    finally:
        capture.release()
        writer.release()

    if processed_frames == 0:
        output_path_obj.unlink(missing_ok=True)
        raise ValueError("Video không có khung hình để phân tích.")

    uniform_groups = [
        {"name": name, "person_count": len(group["track_ids"]), "track_ids": sorted(group["track_ids"])}
        for name, group in groups.items()
        if group["track_ids"]
    ]
    return {
        "processed_frames": processed_frames,
        "duration_seconds": round(processed_frames / fps, 2),
        "people_count": len(seen_tracks[PERSON_CLASS]),
        "vehicle_counts": {name: len(track_ids) for name, track_ids in vehicle_counts.items()},
        "uniform_groups": uniform_groups,
        "events": zone_events,
    }
