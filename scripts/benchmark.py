"""Compare detector models on identical local frames, not an accuracy claim."""

import json
import time

import cv2
import numpy as np
import torch
from ultralytics import YOLO

from schoolguard.config import Settings

settings = Settings()
root = settings.runtime / "evaluation"
samples = json.loads((root / "samples.json").read_text())
torch.set_num_threads(4)
cv2.setNumThreads(2)
report = []
for name, size in [("yolo11n", 640), ("yolo11s", 640), ("yolo11s", 960)]:
    model = YOLO(str(settings.models / (name + ".pt")))
    model.predict(
        np.zeros((480, 856, 3), dtype=np.uint8),
        imgsz=size,
        classes=[0],
        verbose=False,
        device="cpu",
    )
    results = []
    for sample in samples:
        image = cv2.imread(str(root / sample["image"]))
        start = time.perf_counter()
        result = model.predict(
            image, imgsz=size, classes=[0], conf=0.35, iou=0.6, verbose=False, device="cpu"
        )[0]
        elapsed = (time.perf_counter() - start) * 1000
        boxes = result.boxes.xyxy.tolist()
        results.append(
            {
                "scene": sample["scene"],
                "boxes": boxes,
                "confidence": result.boxes.conf.tolist(),
                "latency_ms": round(elapsed, 2),
            }
        )
        cv2.imwrite(str(root / f"{name}-{size}-scene-{sample['scene']:02}.jpg"), result.plot())
    record = {
        "model": name,
        "size": size,
        "mean_ms": round(float(np.mean([r["latency_ms"] for r in results])), 2),
        "results": results,
    }
    report.append(record)
    print(
        json.dumps(
            {
                "model": name,
                "size": size,
                "mean_ms": record["mean_ms"],
                "counts": [len(r["boxes"]) for r in results],
            }
        ),
        flush=True,
    )
(root / "benchmark.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
