"""Local-video worker: bounded memory, normalized frame metadata and durable event outbox."""

from __future__ import annotations

import json
import math
import subprocess
import time
import uuid
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from .detector import Detector, YoloDetector
from .models import Config, Detection, RuleResult
from .rules import ZoneMonitor


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def write_json_line(handle, value: dict) -> None:
    handle.write(json.dumps(value, ensure_ascii=False, allow_nan=False) + "\n")
    handle.flush()


def render(
    frame: np.ndarray,
    config: Config,
    detections: list[Detection],
    result: RuleResult,
    timestamp: float,
) -> np.ndarray:
    out = frame.copy()
    h, w = out.shape[:2]
    if config.redact_people:
        for detection in detections:
            x1, y1, x2, y2 = detection.bbox
            a, b, c, d = (
                int(x1 * w),
                int(y1 * h),
                min(w, math.ceil(x2 * w)),
                min(h, math.ceil(y2 * h)),
            )
            crop = out[b:d, a:c]
            if crop.size:
                small = cv2.resize(crop, (max(1, (c - a) // 24), max(1, (d - b) // 24)))
                out[b:d, a:c] = cv2.resize(small, (c - a, d - b), interpolation=cv2.INTER_NEAREST)
    for zone in config.zones:
        pts = np.asarray([[x * (w - 1), y * (h - 1)] for x, y in zone.polygon], dtype=np.int32)
        color = (
            (0, 0, 255)
            if any(z == zone.zone_id for z, _ in result.alerting_tracks)
            else (0, 165, 255)
        )
        cv2.polylines(out, [pts], True, color, 2)
        cv2.putText(out, zone.zone_id, tuple(pts[0]), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    inside_indices = {i for members in result.zone_members.values() for i in members}
    alert_ids = {tid for _, tid in result.alerting_tracks}
    for i, detection in enumerate(detections):
        x1, y1, x2, y2 = detection.bbox
        a, b, c, d = int(x1 * w), int(y1 * h), int(x2 * w), int(y2 * h)
        color = (
            (0, 0, 255)
            if detection.track_id in alert_ids
            else (0, 165, 255)
            if i in inside_indices
            else (80, 200, 80)
        )
        cv2.rectangle(out, (a, b), (c, d), color, 2)
        label = f"person #{detection.track_id} {detection.confidence:.2f}"
        cv2.putText(out, label, (a, max(15, b - 5)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, color, 1)
    cv2.putText(
        out,
        f"t={timestamp:.2f}s people={len(detections)}",
        (8, 22),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (255, 255, 255),
        1,
    )
    if result.alerting_tracks:
        cv2.putText(
            out,
            "RESTRICTED ZONE INTRUSION",
            (8, h - 15),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
        )
    return out


def browser_video(raw_path: Path) -> tuple[Path, bool]:
    """Produce H.264 if available, and explicitly report fallback to MPEG-4."""
    import imageio_ffmpeg

    destination = raw_path.with_name("annotated.mp4")
    conversion = subprocess.run(
        [
            imageio_ffmpeg.get_ffmpeg_exe(),
            "-y",
            "-loglevel",
            "error",
            "-i",
            str(raw_path),
            "-vf",
            "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(destination),
        ],
        capture_output=True,
        timeout=120,
        check=False,
    )
    if conversion.returncode == 0 and destination.exists():
        raw_path.unlink()
        return destination, True
    return raw_path, False


def process_video(
    source: Path,
    config: Config,
    output_root: Path,
    *,
    detector: Detector | None = None,
    event_sink: Callable[[dict], None] | None = None,
    save_video: bool = True,
    max_input_frames: int | None = None,
) -> dict:
    """Create a unique run directory; event_sink executes after snapshot + local event persist.

    source is a local file only. Backend should enqueue this blocking function in a
    worker process. Instantiate a fresh detector per call; do not share trackers.
    Callback failures fail the run, but emitted events remain available for replay.
    """
    source = Path(source)
    if not source.is_file():
        raise FileNotFoundError(f"Local video does not exist: {source}")
    cap = cv2.VideoCapture(str(source))
    writer = None
    run_dir = None
    started = time.perf_counter()
    try:
        if not cap.isOpened():
            raise ValueError(f"Cannot open video: {source}")
        fps = cap.get(cv2.CAP_PROP_FPS)
        if not math.isfinite(fps) or fps <= 0:
            raise ValueError("Video FPS is invalid; re-encode video with a known frame rate")
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        detector = detector if detector is not None else YoloDetector(config)
        run_id = uuid.uuid4().hex
        run_dir = Path(output_root) / run_id
        run_dir.mkdir(parents=True, exist_ok=False)
        (run_dir / "snapshots").mkdir()
        (run_dir / "config.json").write_text(
            json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        monitor = ZoneMonitor(config)
        frames, events, inference_ms, peak_people = 0, 0, 0.0, 0
        unique_people: set[int] = set()
        input_frames, last_ts = 0, 0.0
        video_result, browser_playable = None, False
        with (
            (run_dir / "events.jsonl").open("w", encoding="utf-8") as event_file,
            (run_dir / "frames.jsonl").open("w", encoding="utf-8") as frame_file,
        ):
            index = -1
            while cap.grab():
                index += 1
                input_frames += 1
                if max_input_frames is not None and input_frames > max_input_frames:
                    raise ValueError("Video exceeds the configured hard frame limit")
                if index % config.frame_stride:
                    continue
                ok, frame = cap.retrieve()
                if not ok:
                    raise RuntimeError(f"Failed to decode frame {index}")
                # Local constant-frame-rate video: time must not depend on machine speed.
                timestamp = index / fps
                last_ts = timestamp
                t0 = time.perf_counter()
                detections = detector.detect(frame)
                elapsed = (time.perf_counter() - t0) * 1000
                result = monitor.update(timestamp, detections)
                inference_ms += elapsed
                frames += 1
                peak_people = max(peak_people, len(detections))
                unique_people.update(
                    detection.track_id
                    for detection in detections
                    if detection.track_id is not None
                )
                visual = render(frame, config, detections, result, timestamp)
                event_ids = []
                for intrusion in result.intrusions:
                    event_id = uuid.uuid4().hex
                    snapshot = Path("snapshots") / f"{event_id}.jpg"
                    if not cv2.imwrite(str(run_dir / snapshot), visual):
                        raise OSError("Cannot write evidence snapshot")
                    event = {
                        "schema_version": "1.0",
                        "event_id": event_id,
                        "run_id": run_id,
                        "camera_id": config.camera_id,
                        "zone_id": intrusion.zone_id,
                        "event_type": "person_in_restricted_zone",
                        "severity": "high",
                        "detected_at": utc_now(),
                        "video_time_seconds": round(timestamp, 6),
                        "frame_index": index,
                        "track_id": intrusion.detection.track_id,
                        "confidence": intrusion.detection.confidence,
                        "bbox": list(intrusion.detection.bbox),
                        "anchor": config.anchor,
                        "dwell_seconds": round(intrusion.dwell_seconds, 6),
                        "evidence": {
                            "path": snapshot.as_posix(),
                            "media_type": "image/jpeg",
                            "redacted": config.redact_people,
                        },
                    }
                    write_json_line(event_file, event)
                    events += 1
                    event_ids.append(event_id)
                    if event_sink:
                        event_sink(event)
                write_json_line(
                    frame_file,
                    {
                        "schema_version": "1.0",
                        "run_id": run_id,
                        "camera_id": config.camera_id,
                        "frame_index": index,
                        "video_time_seconds": round(timestamp, 6),
                        "frame_width": frame.shape[1],
                        "frame_height": frame.shape[0],
                        "inference_ms": round(elapsed, 3),
                        "person_count": len(detections),
                        "zone_counts": {
                            z: len(members) for z, members in result.zone_members.items()
                        },
                        "detections": [
                            asdict(d)
                            | {
                                "zone_ids": [
                                    z for z, members in result.zone_members.items() if i in members
                                ],
                                "alerting": any(
                                    tid == d.track_id for _, tid in result.alerting_tracks
                                ),
                            }
                            for i, d in enumerate(detections)
                        ],
                        "event_ids": event_ids,
                    },
                )
                if save_video:
                    if writer is None:
                        raw = run_dir / "annotated.raw.mp4"
                        writer = cv2.VideoWriter(
                            str(raw),
                            cv2.VideoWriter_fourcc(*"mp4v"),
                            fps / config.frame_stride,
                            (frame.shape[1], frame.shape[0]),
                        )
                        if not writer.isOpened():
                            raise OSError("Cannot create annotated video")
                    writer.write(visual)
            if frames == 0:
                raise ValueError("Video contains no decodable frames")
            if total_frames > 0 and input_frames < total_frames:
                raise RuntimeError("Video stopped before declared frame count (possibly corrupt)")
        if writer is not None:
            writer.release()
            writer = None
            try:
                video_result, browser_playable = browser_video(raw)
            except (OSError, RuntimeError, subprocess.TimeoutExpired):
                video_result = raw
        wall = time.perf_counter() - started
        summary = {
            "schema_version": "1.0",
            "status": "completed",
            "run_id": run_id,
            "camera_id": config.camera_id,
            "source_name": source.name,
            "source_fps": fps,
            "processed_frames": frames,
            "input_frames": input_frames,
            "last_video_time_seconds": last_ts,
            "event_count": events,
            "peak_people": peak_people,
            "unique_people": len(unique_people),
            "mean_inference_ms": round(inference_ms / frames, 3),
            "processing_fps": round(frames / max(wall, 1e-9), 3),
            "wall_seconds": round(wall, 3),
            "annotated_video": video_result.name if video_result else None,
            "browser_playable": browser_playable,
            "completed_at": utc_now(),
            "output_dir": str(run_dir.resolve()),
        }
        (run_dir / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return summary
    except Exception as error:
        if run_dir is not None:
            (run_dir / "failure.json").write_text(
                json.dumps(
                    {
                        "status": "failed",
                        "error_type": type(error).__name__,
                        "message": str(error),
                        "failed_at": utc_now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        raise
    finally:
        cap.release()
        if writer is not None:
            writer.release()
