"""Experimental weapon detection with temporal confirmation.

The model predicts visible objects, not intent or criminal behavior.  Alerts
must always be reviewed by a person.
"""

import hashlib
import json
import os
from pathlib import Path

import cv2

from .behavior import BehaviorEngine
from .tracking import overlap


CATEGORY_BY_LABEL = {
    "gun": "firearm",
    "pistol": "firearm",
    "handgun": "firearm",
    "rifle": "firearm",
    "shotgun": "firearm",
    "knife": "blade",
    "kitchen knife": "blade",
    "dagger": "blade",
    "baseball bat": "blunt_object",
}


def selected_classes(names):
    """Resolve class IDs from checkpoint labels; class ordering is not assumed."""
    items = names.items() if isinstance(names, dict) else enumerate(names)
    return {int(index): CATEGORY_BY_LABEL[str(label).strip().lower()]
            for index, label in items
            if str(label).strip().lower() in CATEGORY_BY_LABEL}


class WeaponDetector:
    def __init__(self, settings, config):
        import torch
        from ultralytics import YOLO

        path = settings.models / "weapon-gun-knife-v1.pt"
        manifest_path = settings.models / "weapon-model.json"
        if not path.is_file() or not manifest_path.is_file():
            raise ValueError("Thiếu model hung khí. Chạy python scripts/download_weapon_model.py.")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.checkpoint_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        if self.checkpoint_sha256 != manifest.get("sha256"):
            raise ValueError("Weapon model manifest/checksum mismatch")
        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        self.model = YOLO(str(path))
        self.classes = selected_classes(self.model.names)
        if not self.classes:
            raise ValueError("Model hung khí không có lớp được LH25 hỗ trợ.")
        self.config = config
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

    def _infer(self, frame):
        result = self.model.predict(
            frame, classes=list(self.classes), conf=max(.08, self.config.confidence * .3),
            iou=.5, imgsz=self.config.image_size, device=self.device,
            verbose=False, max_det=50,
        )[0]
        if result.boxes is None:
            return []
        output = []
        for box, confidence, class_id in zip(
                result.boxes.xyxyn.tolist(), result.boxes.conf.tolist(),
                result.boxes.cls.int().tolist()):
            label = str(self.model.names[class_id])
            output.append({
                "kind": "weapon",
                "category": self.classes[class_id],
                "label": label,
                "confidence": round(float(confidence), 4),
                "bbox": [max(0., min(1., float(value))) for value in box],
            })
        return output

    def __call__(self, frame, people=None):
        # Weapons in surveillance footage are tiny.  Person crops make them
        # larger for the detector and avoid alerting on unrelated background
        # objects.  No visible person means no actionable weapon episode.
        if people is None:
            return self._infer(frame)
        height, width = frame.shape[:2]
        candidates = []
        for person in sorted(people, key=lambda item: -item.get("confidence", 0))[:8]:
            x1, y1, x2, y2 = person["bbox"]
            pad_x, pad_y = (x2 - x1) * .15, (y2 - y1) * .1
            left, top = max(0, int((x1 - pad_x) * width)), max(0, int((y1 - pad_y) * height))
            right, bottom = min(width, int((x2 + pad_x) * width)), min(height, int((y2 + pad_y) * height))
            if right - left < 32 or bottom - top < 32:
                continue
            crop = frame[top:bottom, left:right]
            for detection in self._infer(crop):
                a, b, c, d = detection["bbox"]
                candidates.append({
                    **detection,
                    "bbox": [(left + a * (right-left)) / width,
                             (top + b * (bottom-top)) / height,
                             (left + c * (right-left)) / width,
                             (top + d * (bottom-top)) / height],
                })
        kept = []
        for detection in sorted(candidates, key=lambda item: -item["confidence"]):
            if not any(previous["category"] == detection["category"]
                       and overlap(previous["bbox"], detection["bbox"]) >= .45
                       for previous in kept):
                kept.append(detection)
        return kept


class WeaponEngine:
    """Conservatively confirm repeated, strong observations of the same object."""

    def __init__(self, max_gap=.75, cooldown=10.0, required_count=4,
                 minimum_peak_confidence=.8, minimum_duration=.6,
                 strong_threshold=.7, minimum_strong_count=2,
                 minimum_mean_confidence=.55):
        self.max_gap, self.cooldown, self.required_count = max_gap, cooldown, required_count
        self.minimum_peak_confidence = minimum_peak_confidence
        self.minimum_duration = minimum_duration
        self.strong_threshold = strong_threshold
        self.minimum_strong_count = minimum_strong_count
        self.minimum_mean_confidence = minimum_mean_confidence
        self.tracks, self.next_id, self.last_time = {}, -200, -1.0
        self.last_sent = -1000.0
        self.confirmed = []

    def update(self, detections, timestamp):
        if timestamp <= self.last_time:
            raise ValueError("Frame time must increase")
        self.last_time = timestamp
        self.confirmed = []
        self.tracks = {key: state for key, state in self.tracks.items()
                       if timestamp - state["last"] <= self.max_gap + 1e-9}
        used, alerts = set(), []
        for detection in sorted(detections, key=lambda item: -item["confidence"]):
            matches = [(overlap(detection["bbox"], state["bbox"]), key)
                       for key, state in self.tracks.items()
                       if key not in used and state["category"] == detection["category"]]
            score, track = max(matches, default=(0., None))
            if score < .15:
                track = self.next_id
                self.next_id -= 1
                self.tracks[track] = {**detection, "start": timestamp, "last": timestamp,
                                      "count": 0, "strong_count": 0,
                                      "confidence_sum": 0., "peak_confidence": 0.,
                                      "emitted": False}
            state = self.tracks[track]
            state.update(bbox=detection["bbox"], last=timestamp,
                         confidence=max(state["confidence"], detection["confidence"]),
                         peak_confidence=max(state["peak_confidence"], detection["confidence"]),
                         label=detection["label"], count=state["count"] + 1,
                         strong_count=state["strong_count"] +
                                      int(detection["confidence"] >= self.strong_threshold),
                         confidence_sum=state["confidence_sum"] + detection["confidence"])
            used.add(track)
            duration = timestamp - state["start"]
            if (state["count"] >= self.required_count
                    and duration + 1e-9 >= self.minimum_duration
                    and state["peak_confidence"] >= self.minimum_peak_confidence
                    and state["strong_count"] >= self.minimum_strong_count
                    and state["confidence_sum"] / state["count"] >= self.minimum_mean_confidence):
                confirmed = {**detection, "confidence": round(state["peak_confidence"], 4)}
                self.confirmed.append(confirmed)
                if not state["emitted"] and timestamp - self.last_sent >= self.cooldown:
                    state["emitted"] = True
                    self.last_sent = timestamp
                    alerts.append(BehaviorEngine.alert(
                        "weapon", {**confirmed, "track_id": track},
                        duration,
                        {"reason": "weapon_object_temporally_confirmed",
                         "label": detection["label"],
                         "category": detection["category"],
                         "onset_timestamp": state["start"],
                         "confirmed_timestamp": timestamp,
                         "temporal_observations": state["count"],
                         "peak_confidence": round(state["peak_confidence"], 4),
                         "mean_confidence": round(state["confidence_sum"] / state["count"], 4),
                         "review_required": True,
                         "experimental": True,
                         "not_intent_classification": True},
                    ))
        self.tracks = {key: state for key, state in self.tracks.items() if key in used}
        return alerts


def draw_weapons(image, detections):
    height, width = image.shape[:2]
    for detection in detections:
        x1, y1, x2, y2 = [int(value * (width if index % 2 == 0 else height))
                           for index, value in enumerate(detection["bbox"])]
        cv2.rectangle(image, (x1, y1), (x2, y2), (20, 20, 245), 3)
        cv2.putText(image, f"POSSIBLE WEAPON? {detection['confidence']:.2f}",
                    (x1, max(20, y1 - 7)), cv2.FONT_HERSHEY_SIMPLEX, .55,
                    (20, 20, 245), 2, cv2.LINE_AA)
