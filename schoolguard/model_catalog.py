"""Supported checkpoints and product access; task names describe real capabilities only."""

from pathlib import Path


# The COCO checkpoints detect people/objects, not fire, weapons, or identities.
# Those capabilities use separate, explicitly configured detectors.
MODELS = {
    "yolov8n": ("YOLO8 · Person / vật thể", "free", "detect", "standard"),
    "yolov8n-pose": ("YOLO8 · Pose / nghi té ngã", "free", "pose", "standard"),
    "yolov9t": ("YOLO9 · Person / vật thể", "free", "detect", "standard"),
    "yolov10n": ("YOLO10 · Person / vật thể", "free", "detect", "standard"),
    "yolo11n": ("YOLO11 · Person (nhẹ)", "pro_local", "detect", "standard"),
    "yolo11s": ("YOLO11 · Person (chi tiết)", "pro_local", "detect", "standard"),
    "yolo11n-pose": ("YOLO11 · Pose / hành vi", "pro_local", "pose", "standard"),
    "yolo12n": ("YOLO12 · Research (vật thể)", "pro_local", "detect", "research"),
    "yolo26n": ("YOLO26 · Person / vật thể", "pro_local", "detect", "experimental"),
    "yolo26s": ("YOLO26 · Person (chi tiết)", "pro_local", "detect", "experimental"),
    "yolo26n-pose": ("YOLO26 · Pose / hành vi", "pro_local", "pose", "experimental"),
    "schoolguard-person-v1": ("LH25 · Person fine-tune", "pro_local", "detect", "experimental"),
}


def requires_pro(model: str) -> bool:
    return MODELS[model][1] == "pro_local"


def catalog(model_dir: Path) -> list[dict]:
    return [
        {"id": name, "label": label, "tier": tier, "task": task,
         "maturity": maturity, "available": (model_dir / f"{name}.pt").is_file()}
        for name, (label, tier, task, maturity) in MODELS.items()
    ]
