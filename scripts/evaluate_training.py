"""Held-out fixed-threshold baseline/candidate comparison and fail-closed promotion."""

import hashlib
import json
import shutil
import time

import cv2
import numpy as np

from schoolguard.config import Settings
from scripts.score_spotcheck import iou


def metrics(tp, fp, fn):
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    return {
        "tp": tp,
        "fp": fp,
        "fn": fn,
        "precision": precision,
        "recall": recall,
        "f1": 2 * precision * recall / (precision + recall) if precision + recall else 0.0,
    }


def compare(boxes, confidence, truth):
    matched = set()
    tp = fp = 0
    for box, _ in sorted(zip(boxes, confidence), key=lambda x: -x[1]):
        pairs = [(iou(box, t), i) for i, t in enumerate(truth) if i not in matched]
        best = max(pairs, default=(0, -1))
        if best[0] >= 0.5:
            tp += 1
            matched.add(best[1])
        else:
            fp += 1
    return tp, fp, len(truth) - tp


def promotion(candidate, baseline):
    try:
        c, b = candidate["overall"], baseline["overall"]
        cs, bs = candidate["slices"].get("shanghaitech"), baseline["slices"].get("shanghaitech")
        return bool(
            cs
            and bs
            and c["f1"] >= b["f1"] + 0.01
            and c["precision"] >= b["precision"] - 0.01
            and cs["recall"] >= bs["recall"]
            and cs["fp"] <= bs["fp"]
            and 0 < candidate["mean_latency_ms"] <= baseline["mean_latency_ms"] * 1.5
        )
    except (KeyError, TypeError):
        return False


def main():
    import torch
    from ultralytics import YOLO

    settings = Settings()
    data = settings.runtime / "training-data"
    run = settings.runtime / "training-runs/person-adapt-v1"
    manifest = json.loads((data / "manifest.json").read_text())
    test = [x for x in manifest["items"] if x["split"] == "test"]
    weights = run / "weights/best.pt"
    if not (run / "provenance.json").is_file() or not weights.is_file():
        raise RuntimeError("Training must finish before held-out evaluation")
    torch.set_num_threads(4)
    all_results = []
    for name, path in [
        ("yolo11n", settings.models / "yolo11n.pt"),
        ("yolo11s", settings.models / "yolo11s.pt"),
        ("schoolguard-person-v1", weights),
    ]:
        model = YOLO(str(path))
        model.predict(
            np.zeros((480, 856, 3), dtype=np.uint8),
            classes=[0],
            imgsz=640,
            verbose=False,
            device="cpu",
        )
        details = []
        for item in test:
            image = cv2.imread(str(data / "images/test" / (item["name"] + ".jpg")))
            h, w = image.shape[:2]
            truth = []
            for line in (data / "labels/test" / (item["name"] + ".txt")).read_text().splitlines():
                _, x, y, bw, bh = map(float, line.split())
                truth.append(
                    [(x - bw / 2) * w, (y - bh / 2) * h, (x + bw / 2) * w, (y + bh / 2) * h]
                )
            start = time.perf_counter()
            result = model.predict(
                image, classes=[0], conf=0.35, iou=0.6, imgsz=640, verbose=False, device="cpu"
            )[0]
            ms = (time.perf_counter() - start) * 1000
            tp, fp, fn = compare(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(), truth)
            details.append(
                {
                    "name": item["name"],
                    "source": item["source"],
                    "tp": tp,
                    "fp": fp,
                    "fn": fn,
                    "latency_ms": ms,
                }
            )
        slices = {}
        for source in ["coco128", "penn-fudan", "shanghaitech"]:
            items = [x for x in details if x["source"] == source]
            slices[source] = metrics(*(sum(x[k] for x in items) for k in ["tp", "fp", "fn"]))
        record = {
            "model": name,
            "overall": metrics(*(sum(x[k] for x in details) for k in ["tp", "fp", "fn"])),
            "slices": slices,
            "mean_latency_ms": float(np.mean([x["latency_ms"] for x in details])),
            "images": len(details),
            "details": details,
        }
        all_results.append(record)
        print(json.dumps({k: v for k, v in record.items() if k != "details"}), flush=True)
    approved = promotion(all_results[2], all_results[1])
    report = {
        "candidate": "schoolguard-person-v1",
        "default_model": "schoolguard-person-v1" if approved else "yolo11s",
        "promoted": approved,
        "iou_threshold": 0.5,
        "confidence": 0.35,
        "image_size": 640,
        "results": all_results,
        "checkpoint_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
        "dataset_manifest_sha256": hashlib.sha256(
            (data / "manifest.json").read_bytes()
        ).hexdigest(),
        "limitations": [
            "COCO128 already in pretrained COCO training set.",
            "Only three held-out ShanghaiTech frames; subjective labels, not a final benchmark.",
            "Some Penn-Fudan background people may be unannotated.",
            "ShanghaiTech training uses noisy teacher pseudo labels.",
        ],
    }
    shutil.copy2(weights, settings.models / "schoolguard-person-v1.pt")
    (settings.models / "training-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print("PROMOTED=" + str(approved), flush=True)


if __name__ == "__main__":
    main()
