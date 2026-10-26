"""Adapter between the browser's rectangle zones and the BE-1 video worker."""

from __future__ import annotations

import os
from pathlib import Path

import cv2
from schoolguard_ai.models import Config, Zone
from schoolguard_ai.worker import process_video


def can_use_person_worker(zones: list[dict]) -> bool:
    """The BE-1 worker is intentionally person-only for the home MVP."""
    return bool(zones) and all(set(zone.get("classes", [])) == {0} for zone in zones)


def validate_video_duration(
    source: Path,
    *,
    max_seconds: float = 180,
    max_pixels: int = 1920 * 1080,
) -> float:
    capture = cv2.VideoCapture(str(source))
    try:
        if not capture.isOpened():
            raise ValueError("Không mở được video. Hãy thử mã hóa lại file.")
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = float(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = float(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = float(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or fps > 60 or frame_count <= 0:
            raise ValueError("Video phải có FPS hợp lệ và không vượt quá 60 FPS")
        if width <= 0 or height <= 0 or width * height > max_pixels:
            raise ValueError("Video vượt quá độ phân giải Full HD được hỗ trợ")
        duration = frame_count / fps
        if duration > max_seconds:
            raise ValueError(f"Video dài quá {int(max_seconds // 60)} phút")
        return duration
    finally:
        capture.release()


def rectangles_to_config(
    zones: list[dict],
    *,
    source_id: str,
    model: str | None = None,
    dwell_seconds: float | None = None,
) -> Config:
    polygon_zones = tuple(
        Zone(
            zone_id=zone["id"],
            name=zone["name"],
            polygon=(
                (zone["x"], zone["y"]),
                (zone["x"] + zone["width"], zone["y"]),
                (zone["x"] + zone["width"], zone["y"] + zone["height"]),
                (zone["x"], zone["y"] + zone["height"]),
            ),
        )
        for zone in zones
    )
    return Config(
        camera_id=source_id,
        zones=polygon_zones,
        model=model or os.getenv("YOLO_MODEL", "yolo11n.pt"),
        confidence=float(os.getenv("YOLO_CONFIDENCE", "0.35")),
        image_size=int(os.getenv("YOLO_IMAGE_SIZE", "640")),
        frame_stride=int(os.getenv("VIDEO_FRAME_STRIDE", "1")),
        device=os.getenv("YOLO_DEVICE", "cpu"),
        anchor=os.getenv("ZONE_ANCHOR", "bottom"),
        dwell_seconds=(
            dwell_seconds
            if dwell_seconds is not None
            else float(os.getenv("ZONE_DWELL_SECONDS", "5"))
        ),
        missing_grace_seconds=float(os.getenv("TRACK_MISSING_GRACE_SECONDS", "0.5")),
        redact_people=os.getenv("REDACT_PEOPLE", "true").lower() not in {"0", "false", "no"},
    )


def analyze_person_video(
    source: Path,
    output_root: Path,
    zones: list[dict],
    *,
    source_id: str,
) -> dict:
    """Run BE-1 and normalize its output to the existing FE-2 response contract."""
    config = rectangles_to_config(zones, source_id=source_id)
    worker_events: list[dict] = []
    worker_summary = process_video(
        Path(source),
        config,
        Path(output_root),
        event_sink=worker_events.append,
        save_video=True,
        max_input_frames=10_800,
    )
    run_dir = Path(worker_summary["output_dir"])
    zone_names = {zone["id"]: zone["name"] for zone in zones}
    events = []
    for event in worker_events:
        events.append(
            {
                "zone_id": event["zone_id"],
                "zone_name": zone_names.get(event["zone_id"], event["zone_id"]),
                "object_type": "person",
                "track_id": event.get("track_id"),
                "confidence": event.get("confidence"),
                "media_offset_seconds": event.get("video_time_seconds"),
                "image_path": run_dir / event["evidence"]["path"],
            }
        )

    annotated_name = worker_summary.get("annotated_video")
    if not annotated_name:
        raise RuntimeError("BE-1 không tạo được video kết quả")
    return {
        **worker_summary,
        "duration_seconds": round(worker_summary["last_video_time_seconds"], 2),
        "people_count": worker_summary.get("unique_people", worker_summary["peak_people"]),
        "vehicle_counts": {},
        "uniform_groups": [],
        "events": events,
        "engine": "be1-yolo-bytetrack",
        "output_path": run_dir / annotated_name,
    }
