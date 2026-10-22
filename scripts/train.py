"""Run bounded, reproducible CPU transfer learning on prepared person data."""

import argparse
import hashlib
import json
import os

from schoolguard.config import Settings


def main():
    settings = Settings()
    (settings.runtime / "ultralytics").mkdir(parents=True, exist_ok=True)
    os.environ["YOLO_CONFIG_DIR"] = str(settings.runtime / "ultralytics")
    os.environ["OMP_NUM_THREADS"] = "4"
    os.environ["MKL_NUM_THREADS"] = "4"
    import torch
    from ultralytics import YOLO
    from ultralytics import settings as yolo_settings

    yolo_settings.update({"sync": False})
    parser = argparse.ArgumentParser()
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--name", default="person-adapt-v1")
    args = parser.parse_args()
    torch.set_num_threads(4)
    data = settings.runtime / "training-data"
    # Rebuild the path after moving the project; labels/manifest remain unchanged.
    import yaml

    config = yaml.safe_load((data / "data.yaml").read_text(encoding="utf-8"))
    config["path"] = str(data.resolve())
    (data / "data.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    snapshot = hashlib.sha256((data / "manifest.json").read_bytes()).hexdigest()
    model = YOLO(str(settings.models / "yolo11n.pt"))
    model.train(
        data=str(data / "data.yaml"),
        epochs=args.epochs,
        imgsz=512,
        batch=8,
        device="cpu",
        workers=0,
        seed=42,
        deterministic=True,
        freeze=10,
        optimizer="AdamW",
        lr0=0.0005,
        lrf=0.1,
        warmup_epochs=1,
        patience=5,
        mosaic=0.3,
        close_mosaic=3,
        mixup=0,
        degrees=0,
        translate=0.05,
        scale=0.2,
        fliplr=0.5,
        cache=False,
        plots=True,
        project=str(settings.runtime / "training-runs"),
        name=args.name,
        exist_ok=False,
        save=True,
        verbose=False,
    )
    run = model.trainer.save_dir
    (run / "provenance.json").write_text(
        json.dumps(
            {
                "dataset_manifest_sha256": snapshot,
                "starting_model": "yolo11n.pt",
                "seed": 42,
                "epochs_requested": args.epochs,
                "device": "cpu",
                "label_note": "ShanghaiTech train includes teacher pseudo labels; evaluation excludes those scenes.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print("TRAINING_FINISHED " + str(run), flush=True)


if __name__ == "__main__":
    main()
