"""Real-model smoke using an authorized local image; not an AI accuracy benchmark."""

import argparse
import json
import uuid
from pathlib import Path

import cv2
import numpy as np

from schoolguard_ai.models import Config, Zone
from schoolguard_ai.worker import process_video


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True, type=Path)
    parser.add_argument("--model", default="yolov8n.pt")
    parser.add_argument("--output", type=Path, default=Path("outputs/smoke"))
    args = parser.parse_args()
    frame = cv2.imread(str(args.image))
    if frame is None:
        parser.error("Cannot read local image")
    height, width = frame.shape[:2]
    scale = min(1.0, 640 / max(height, width))
    frame = cv2.resize(
        frame, (max(2, int(width * scale) // 2 * 2), max(2, int(height * scale) // 2 * 2))
    )
    args.output.mkdir(parents=True, exist_ok=True)
    source = args.output / f"smoke-source-{uuid.uuid4().hex}.mp4"
    writer = cv2.VideoWriter(
        str(source), cv2.VideoWriter_fourcc(*"mp4v"), 10, (frame.shape[1], frame.shape[0])
    )
    if not writer.isOpened():
        raise RuntimeError("Cannot create smoke clip")
    try:
        for _ in range(15):
            writer.write(frame)
    finally:
        writer.release()
    config = Config(
        "SMOKE-CAM",
        (Zone("SMOKE-ZONE", "Full frame", ((0, 0), (1, 0), (1, 1), (0, 1))),),
        model=args.model,
        dwell_seconds=0.5,
    )
    summary = process_video(source, config, args.output)
    if summary["event_count"] < 1:
        raise RuntimeError(
            "Smoke failed: no tracked person alert; choose an image with clear people"
        )
    blank = args.output / f"smoke-blank-{uuid.uuid4().hex}.mp4"
    writer = cv2.VideoWriter(
        str(blank), cv2.VideoWriter_fourcc(*"mp4v"), 10, (frame.shape[1], frame.shape[0])
    )
    if not writer.isOpened():
        raise RuntimeError("Cannot create blank smoke clip")
    try:
        for _ in range(10):
            writer.write(np.zeros_like(frame))
    finally:
        writer.release()
    negative = process_video(blank, config, args.output, save_video=False)
    if negative["event_count"] != 0 or negative["peak_people"] != 0:
        raise RuntimeError("Smoke failed: blank video unexpectedly detected people")
    print(json.dumps({"positive": summary, "negative": negative}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
