import hashlib
import os
import time
from pathlib import Path


class PersonDetector:
    def __init__(self, settings, config, classes=None):
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        path = settings.models / (config.model + ".pt")
        if not path.is_file():
            raise ValueError(f"Thiếu {path.name}. Chạy python scripts/download_models.py trước.")
        self.model = YOLO(str(path))
        self.checkpoint_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.config = config
        self.classes = [0] if classes is None else classes
        self.confirmed_people = {}
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

    def reset_tracking(self):
        self.confirmed_people.clear()
        predictor = getattr(self.model, "predictor", None)
        for tracker in getattr(predictor, "trackers", []):
            tracker.reset()

    def __call__(self, frame):
        c = self.config
        results = self.model.track(
            frame,
            persist=True,
            classes=self.classes,
            conf=0.1,
            iou=0.6,
            imgsz=c.image_size,
            tracker=str(Path(__file__).with_name("bytetrack.yaml")),
            device=self.device,
            verbose=False,
            max_det=200,
        )
        boxes = results[0].boxes
        detections = []
        if boxes is None:
            return detections
        ids = boxes.id.int().tolist() if boxes.id is not None else [None] * len(boxes)
        keypoints = results[0].keypoints
        stamp = time.monotonic()
        self.confirmed_people = {key: last for key, last in self.confirmed_people.items()
                                 if stamp - last <= 2.5}
        for index, (xyxy, confidence, track, label) in enumerate(
            zip(boxes.xyxyn.tolist(), boxes.conf.tolist(), ids, boxes.cls.tolist())
        ):
            # A partly occluded body can still have a real, low-confidence box
            # matched to an established person. Keep that observation, never
            # synthesize a box for a person the detector cannot see at all.
            established_person = int(label) == 0 and track in self.confirmed_people
            threshold = max(0.1, c.confidence * 0.5) if established_person else c.confidence
            if confidence < threshold:
                continue
            bbox = [max(0.0, min(1.0, float(x))) for x in xyxy]
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            if int(label) == 0 and track is not None:
                self.confirmed_people[track] = stamp
            item = {"class_id": int(label), "label": self.model.names[int(label)], "track_id": track, "confidence": round(confidence, 4), "bbox": bbox}
            if keypoints is not None and keypoints.conf is not None:
                item["keypoints"] = [
                    [float(x), float(y), float(p)]
                    for (x, y), p in zip(
                        keypoints.xyn[index].tolist(), keypoints.conf[index].tolist()
                    )
                ]
            detections.append(item)
        return detections
