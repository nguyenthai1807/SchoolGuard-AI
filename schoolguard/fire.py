"""Experimental fire/smoke inference and spatially matched temporal confirmation."""

import hashlib
import json

import cv2
import numpy as np

from .behavior import BehaviorEngine


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1])
    )
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


def decode(output, original_shape, scale, left, top, confidence=0.5):
    if output.shape != (1, 6, 2100) or not np.isfinite(output).all():
        raise ValueError("Unsupported or invalid fire model output")
    rows = output[0].T
    h, w = original_shape[:2]
    results = []
    for label, kind in enumerate(("fire", "smoke")):
        boxes, scores = [], []
        for row in rows:
            if row[4 + label] < confidence or np.argmax(row[4:]) != label:
                continue
            x, y, bw, bh = row[:4]
            x1, y1 = max(0, (x - bw / 2 - left) / scale), max(0, (y - bh / 2 - top) / scale)
            x2, y2 = min(w, (x + bw / 2 - left) / scale), min(h, (y + bh / 2 - top) / scale)
            if x2 <= x1 or y2 <= y1:
                continue
            boxes.append([float(x1), float(y1), float(x2 - x1), float(y2 - y1)])
            scores.append(float(row[4 + label]))
        indices = cv2.dnn.NMSBoxes(boxes, scores, confidence, 0.45)
        for index in np.array(indices).reshape(-1).tolist():
            x, y, bw, bh = boxes[index]
            results.append(
                {
                    "kind": kind,
                    "bbox": [x / w, y / h, (x + bw) / w, (y + bh) / h],
                    "confidence": scores[index],
                }
            )
    return results


class FireDetector:
    def __init__(self, settings):
        path = settings.models / "fire-smoke-v1.onnx"
        metadata = json.loads((settings.models / "fire-model.json").read_text())
        self.checkpoint_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.checkpoint_sha256 != metadata["sha256"] or metadata["classes"] != ["fire", "smoke"]:
            raise ValueError("Fire model manifest/checksum mismatch")
        self.net = cv2.dnn.readNetFromONNX(str(path))

    def __call__(self, frame):
        h, w = frame.shape[:2]
        detections = self.infer(frame)
        # Overlapping tiles preserve small distant smoke at the fixed 320px model input.
        if w > 640:
            tw, th = round(w * 0.6), round(h * 0.6)
            for x, y in ((0, 0), (w - tw, 0), (0, h - th), (w - tw, h - th)):
                for d in self.infer(frame[y : y + th, x : x + tw]):
                    a, b, c, e = d["bbox"]
                    detections.append(
                        {
                            **d,
                            "bbox": [
                                (x + a * tw) / w,
                                (y + b * th) / h,
                                (x + c * tw) / w,
                                (y + e * th) / h,
                            ],
                        }
                    )
        kept = []
        for d in sorted(detections, key=lambda d: -d["confidence"]):
            if not any(
                k["kind"] == d["kind"] and overlap(k["bbox"], d["bbox"]) > 0.45 for k in kept
            ):
                kept.append(d)
        return kept

    def infer(self, frame):
        h, w = frame.shape[:2]
        scale = 320 / max(h, w)
        nw, nh = round(w * scale), round(h * scale)
        left, top = (320 - nw) // 2, (320 - nh) // 2
        image = np.full((320, 320, 3), 114, dtype=np.uint8)
        image[top : top + nh, left : left + nw] = cv2.resize(frame, (nw, nh))
        self.net.setInput(cv2.dnn.blobFromImage(image, 1 / 255.0, (320, 320), swapRB=True))
        return decode(self.net.forward(), frame.shape, scale, left, top)


class FireEngine:
    def __init__(self, dwell=2.0, max_gap=1.5, cooldown=15.0):
        self.dwell, self.max_gap, self.cooldown = dwell, max_gap, cooldown
        self.tracks, self.next_id, self.last_time = {}, -100, -1.0
        self.last_sent_by_kind = {}

    def update(self, detections, timestamp):
        if timestamp <= self.last_time:
            raise ValueError("Frame time must increase")
        self.last_time = timestamp
        self.tracks = {
            k: v for k, v in self.tracks.items() if timestamp - v["last"] <= self.max_gap
        }
        used, alerts = set(), []
        for d in sorted(detections, key=lambda d: -d["confidence"]):
            choices = [
                (overlap(d["bbox"], t["bbox"]), k)
                for k, t in self.tracks.items()
                if k not in used and t["kind"] == d["kind"]
            ]
            match, track = max(choices, default=(0, 0))
            if match < 0.2:
                track = self.next_id
                self.next_id -= 1
                self.tracks[track] = {
                    **d,
                    "start": timestamp,
                    "last": timestamp,
                    "count": 0,
                    "emitted": False,
                }
            state = self.tracks[track]
            state.update(bbox=d["bbox"], last=timestamp, count=state["count"] + 1)
            used.add(track)
            duration = timestamp - state["start"]
            if not state["emitted"] and state["count"] >= 3 and duration + 1e-9 >= self.dwell:
                state["emitted"] = True
                if timestamp - self.last_sent_by_kind.get(d["kind"], -1000) < self.cooldown:
                    continue
                self.last_sent_by_kind[d["kind"]] = timestamp
                alerts.append(
                    BehaviorEngine.alert(
                        d["kind"],
                        {**d, "track_id": track},
                        duration,
                        {
                            "reason": "spatial_overlap_and_temporal_persistence",
                            "not_a_certified_fire_alarm": True,
                        },
                    )
                )
        # Explicit absence resets immediately; missing detections are not positive evidence.
        self.tracks = {k: v for k, v in self.tracks.items() if k in used}
        return alerts


def draw_hazards(image, detections):
    h, w = image.shape[:2]
    for d in detections:
        x1, y1, x2, y2 = [int(v * (w if i % 2 == 0 else h)) for i, v in enumerate(d["bbox"])]
        cv2.rectangle(image, (x1, y1), (x2, y2), (20, 100, 255), 2)
        cv2.putText(
            image,
            f"{d['kind']}? {d['confidence']:.2f}",
            (x1, max(18, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (20, 100, 255),
            2,
        )
