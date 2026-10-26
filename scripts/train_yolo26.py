"""Fine-tune an optional YOLO26 person candidate; never replace production weights."""

import argparse
import hashlib
import json
import os
from pathlib import Path

from schoolguard.config import Settings


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--name", default="yolo26-person-experiment")
    args = parser.parse_args()
    if not 1 <= args.epochs <= 100 or not 1 <= args.batch <= 32:
        parser.error("epochs must be 1..100 and batch must be 1..32")
    if not args.name.replace("-", "").replace("_", "").isalnum():
        parser.error("name may contain only letters, digits, hyphens and underscores")

    settings = Settings()
    data_file = (args.data or settings.runtime / "phone-training/data.yaml").resolve()
    data_dir = data_file.parent
    manifest_file = data_dir / "manifest.json"
    if not data_file.is_file() or not manifest_file.is_file():
        raise RuntimeError("Need prepared, scene-split YOLO data.yaml and manifest.json.")
    manifest = json.loads(manifest_file.read_text(encoding="utf-8"))
    items = manifest.get("items", [])
    scene_sets = {split: {row["scene"] for row in items if row["split"] == split}
                  for split in ("train", "val", "test")}
    if any(not scene_sets[split] for split in scene_sets):
        raise RuntimeError("Train, validation and held-out test scenes must all exist.")
    if any(scene_sets[a] & scene_sets[b] for a, b in (("train", "val"), ("train", "test"), ("val", "test"))):
        raise RuntimeError("Scene leakage between train, val and test splits.")
    for split in scene_sets:
        if not list((data_dir / "images" / split).glob("*.jpg")) or not list((data_dir / "labels" / split).glob("*.txt")):
            raise RuntimeError(f"Missing images or labels for {split}.")
    checkpoint = settings.models / "yolo26n.pt"
    if not checkpoint.is_file():
        raise RuntimeError("Download official yolo26n.pt first: python -m scripts.download_yolo26")
    run_dir = settings.runtime / "training-runs" / args.name
    if run_dir.exists():
        raise RuntimeError(f"Existing training run is preserved: {run_dir}")

    os.environ["YOLO_CONFIG_DIR"] = str(settings.runtime / "ultralytics")
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["MKL_NUM_THREADS"] = "4"
    import torch
    from ultralytics import YOLO, __version__, settings as yolo_settings

    torch.set_num_threads(4)
    yolo_settings.update({"sync": False})
    provenance = {
        "starting_model": "yolo26n.pt", "starting_sha256": hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
        "ultralytics_version": __version__, "dataset_manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
        "data_yaml": str(data_file), "scenes": {key: sorted(value) for key, value in scene_sets.items()},
        "seed": 42, "epochs": args.epochs, "batch": args.batch, "device": "cpu",
        "label_warning": "Train and validation have YOLO11s pseudo labels; test is only 9 reviewed frames. This is an experiment, not a production model.",
    }
    model = YOLO(str(checkpoint))
    model.train(
        data=str(data_file), epochs=args.epochs, imgsz=512, batch=args.batch,
        device="cpu", workers=0, seed=42, deterministic=True, freeze=10,
        optimizer="AdamW", lr0=0.0002, lrf=0.1, warmup_epochs=1,
        mosaic=0.2, close_mosaic=1, mixup=0, cache=False, plots=False,
        project=str(run_dir.parent), name=run_dir.name, exist_ok=False,
        save=True, verbose=False, amp=False,
    )
    actual_dir = Path(model.trainer.save_dir)
    (actual_dir / "provenance.json").write_text(json.dumps(provenance, indent=2), encoding="utf-8")
    print(f"TRAINING_FINISHED {actual_dir}", flush=True)
    print("Checkpoint remains experimental. Run scripts.evaluate_yolo26 before using it.", flush=True)


if __name__ == "__main__":
    main()
