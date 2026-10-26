"""Fetch missing lightweight pretrained checkpoints from official ultralytics/assets.

Run explicitly with the project venv; this never downloads on server startup.
"""

from pathlib import Path

from ultralytics import YOLO
from ultralytics.utils.downloads import attempt_download_asset


ROOT = Path(__file__).resolve().parents[1]
MODELS = ROOT / "models"
OFFICIAL = ("yolov8n", "yolov8n-pose", "yolov9t", "yolov10n", "yolo12n")


def main():
    MODELS.mkdir(exist_ok=True)
    for name in OFFICIAL:
        target = MODELS / f"{name}.pt"
        if not target.is_file():
            print(f"Downloading {name} from ultralytics/assets...", flush=True)
            downloaded = Path(attempt_download_asset(target, repo="ultralytics/assets"))
            if not downloaded.is_file() or downloaded.stat().st_size < 100_000:
                raise RuntimeError(f"Official checkpoint unavailable or incomplete: {name}")
        model = YOLO(str(target))
        expected = "pose" if name.endswith("-pose") else "detect"
        if model.task != expected or not model.names or model.names.get(0) != "person":
            raise RuntimeError(f"Wrong task or label map in {target.name}")
        print(f"Ready: {target.name} ({target.stat().st_size:,} bytes; {model.task})", flush=True)


if __name__ == "__main__":
    main()
