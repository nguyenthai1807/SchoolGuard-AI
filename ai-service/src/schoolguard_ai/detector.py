"""YOLO person detection with explicit ByteTrack and per-run tracker ownership."""

from __future__ import annotations

from typing import Protocol

import numpy as np

from .models import Config, Detection


class Detector(Protocol):
    def detect(self, frame: np.ndarray) -> list[Detection]: ...


class YoloDetector:
    def __init__(self, config: Config):
        from ultralytics import YOLO

        self.config = config
        self.model = YOLO(config.model)
        self.person_ids = [key for key, name in self.model.names.items() if name == "person"]
        if not self.person_ids:
            raise ValueError("The selected model has no person class")

    def detect(self, frame: np.ndarray) -> list[Detection]:
        result = self.model.track(
            frame,
            persist=True,
            tracker="bytetrack.yaml",
            classes=self.person_ids,
            conf=self.config.confidence,
            imgsz=self.config.image_size,
            device=self.config.device,
            verbose=False,
        )[0]
        boxes = result.boxes
        if boxes is None or not len(boxes):
            return []
        height, width = frame.shape[:2]
        xyxy = boxes.xyxy.cpu().numpy()
        scores = boxes.conf.cpu().numpy()
        ids = boxes.id.cpu().numpy() if boxes.id is not None else [None] * len(boxes)
        detections = []
        for box, score, tid in zip(xyxy, scores, ids, strict=True):
            normalized = tuple(
                float(v) for v in np.clip(box / np.array([width, height, width, height]), 0, 1)
            )
            if normalized[2] <= normalized[0] or normalized[3] <= normalized[1]:
                continue
            detections.append(
                Detection(
                    None if tid is None else int(tid),
                    float(score),
                    normalized,
                )
            )
        return detections
