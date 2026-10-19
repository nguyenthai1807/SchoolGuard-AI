import hashlib
import os
from pathlib import Path


class PersonDetector:
    def __init__(self, settings, config):
        import torch
        from ultralytics import YOLO

        torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
        path = settings.models / (config.model + ".pt")
        if not path.is_file():
            raise ValueError(f"Thiếu {path.name}. Chạy python scripts/download_models.py trước.")
        self.model = YOLO(str(path))
        self.checkpoint_sha256 = hashlib.sha256(path.read_bytes()).hexdigest()
        self.config = config
        self.device = "cuda:0" if torch.cuda.is_available() else "cpu"

    def __call__(self, frame):
        c = self.config
        results = self.model.track(
            frame,
            persist=True,
            classes=[0],
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
        for index, (xyxy, confidence, track, label) in enumerate(
            zip(boxes.xyxyn.tolist(), boxes.conf.tolist(), ids, boxes.cls.tolist())
        ):
            if int(label) != 0 or confidence < c.confidence:
                continue
            bbox = [max(0.0, min(1.0, float(x))) for x in xyxy]
            if bbox[2] <= bbox[0] or bbox[3] <= bbox[1]:
                continue
            item = {"track_id": track, "confidence": round(confidence, 4), "bbox": bbox}
            if keypoints is not None and keypoints.conf is not None:
                item["keypoints"] = [
                    [float(x), float(y), float(p)]
                    for (x, y), p in zip(
                        keypoints.xyn[index].tolist(), keypoints.conf[index].tolist()
                    )
                ]
            detections.append(item)
        return detections
