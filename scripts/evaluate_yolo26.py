"""Compare experimental YOLO26 person weights to the current YOLO11s baseline."""

import argparse
import hashlib
import json
import statistics
import time
from pathlib import Path

from schoolguard.config import Settings
from scripts.evaluate_training import compare, metrics


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--name", default="yolo26-person-experiment")
    args = parser.parse_args()
    settings = Settings()
    data = settings.runtime / "phone-training"
    run = (settings.runtime / "training-runs" / args.name).resolve()
    if not run.is_relative_to((settings.runtime / "training-runs").resolve()):
        parser.error("run name must stay under runtime/training-runs")
    weights = run / "weights/best.pt"
    if not weights.is_file() or not (run / "provenance.json").is_file():
        raise RuntimeError("YOLO26 training must finish before evaluation.")
    manifest_file = data / "manifest.json"
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    provenance = json.loads((run / "provenance.json").read_text(encoding="utf-8"))
    if provenance["dataset_manifest_sha256"] != hashlib.sha256(manifest_file.read_bytes()).hexdigest():
        raise RuntimeError("Dataset manifest changed after training.")
    test = [row for row in manifest["items"] if row["split"] == "test"]
    if not test or not all(row.get("reviewed") for row in test):
        raise RuntimeError("Held-out test labels require review before evaluation.")
    import cv2
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(4)
    cv2.setNumThreads(2)
    records = []
    for name, checkpoint in (("yolo11s", settings.models / "yolo11s.pt"), ("yolo26n-candidate", weights)):
        model = YOLO(str(checkpoint))
        details = []
        for row in test:
            image = cv2.imread(str(data / "images/test" / (row["name"] + ".jpg")))
            if image is None:
                raise RuntimeError(f"Missing test image: {row['name']}")
            height, width = image.shape[:2]
            truth = []
            for line in (data / "labels/test" / (row["name"] + ".txt")).read_text().splitlines():
                cls, x, y, w, h = map(float, line.split())
                if int(cls) == 0:
                    truth.append([(x-w/2)*width, (y-h/2)*height, (x+w/2)*width, (y+h/2)*height])
            started = time.perf_counter()
            boxes = model.predict(image, classes=[0], conf=0.35, iou=0.6,
                                  imgsz=640, device="cpu", verbose=False)[0].boxes
            elapsed = (time.perf_counter() - started) * 1000
            tp, fp, fn = compare(boxes.xyxy.tolist(), boxes.conf.tolist(), truth)
            details.append({"name": row["name"], "tp": tp, "fp": fp, "fn": fn,
                            "truth_count": len(truth), "predicted_count": len(boxes),
                            "latency_ms": round(elapsed, 1)})
        records.append({"name": name, "metrics": metrics(*(sum(d[key] for d in details)
                        for key in ("tp", "fp", "fn"))),
                        "count_mae": sum(abs(d["truth_count"]-d["predicted_count"]) for d in details)/len(details),
                        "median_latency_ms": statistics.median(d["latency_ms"] for d in details),
                        "details": details})
    baseline, candidate = records
    gate = (candidate["metrics"]["f1"] >= baseline["metrics"]["f1"]
            and candidate["metrics"]["recall"] >= baseline["metrics"]["recall"]
            and candidate["metrics"]["fp"] <= baseline["metrics"]["fp"]
            and candidate["count_mae"] <= baseline["count_mae"]
            and candidate["median_latency_ms"] <= baseline["median_latency_ms"] * 1.5)
    result = {"test_images": len(test), "technical_gate_passed": gate, "promoted": False,
              "note": "Only 9 reviewed frames from 3 outdoor scenes. Requires larger, independently labeled indoor video/webcam tests before promotion.",
              "checkpoint_sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
              "records": records}
    (run / "evaluation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "records"}, indent=2))
    for record in records:
        print(json.dumps({key: value for key, value in record.items() if key != "details"}))


if __name__ == "__main__":
    main()
