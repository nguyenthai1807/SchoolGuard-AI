"""Download and validate the official Ultralytics Open Images checkpoint."""

import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlretrieve

from ultralytics import YOLO

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from schoolguard.weapons import selected_classes

URL = "https://huggingface.co/cosgun99/gun-knife-yolo11n/resolve/main/best.pt"
TARGET = ROOT / "models" / "weapon-gun-knife-v1.pt"
MANIFEST = ROOT / "models" / "weapon-model.json"


def main():
    TARGET.parent.mkdir(exist_ok=True)
    if not TARGET.is_file():
        temporary = TARGET.with_suffix(".download")
        print("Downloading gun/knife YOLO11n checkpoint from its model repository...", flush=True)
        urlretrieve(URL, temporary)
        temporary.replace(TARGET)
    model = YOLO(str(TARGET))
    classes = selected_classes(model.names)
    labels = {str(index): str(model.names[index]) for index in classes}
    required = {"gun", "knife"}
    if not required.issubset({label.lower() for label in labels.values()}):
        raise RuntimeError(f"Unexpected Open Images class names: {labels}")
    manifest = {
        "source_url": URL,
        "sha256": hashlib.sha256(TARGET.read_bytes()).hexdigest(),
        "selected_classes": labels,
        "model_card": "https://huggingface.co/cosgun99/gun-knife-yolo11n",
        "model_repository_license": "MIT",
        "runtime_license": "AGPL-3.0-or-Ultralytics-Enterprise",
        "license_url": "https://www.ultralytics.com/license",
        "downloaded_at": datetime.now(timezone.utc).isoformat(),
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Ready: {TARGET.name} ({TARGET.stat().st_size:,} bytes)")
    print(f"Selected classes: {', '.join(labels.values())}")


if __name__ == "__main__":
    main()
