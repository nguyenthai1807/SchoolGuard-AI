"""Download public pretrained weights; no private data is uploaded."""

from pathlib import Path
from urllib.request import urlretrieve

root = Path(__file__).resolve().parents[1] / "models"
root.mkdir(exist_ok=True)
for name in ["yolo11n", "yolo11s", "yolo11n-pose"]:
    target = root / (name + ".pt")
    if not target.is_file():
        temp = target.with_suffix(".download")
        print(f"Downloading {name}...", flush=True)
        urlretrieve(
            f"https://github.com/ultralytics/assets/releases/download/v8.3.0/{name}.pt", temp
        )
        temp.replace(target)
    print(f"Ready: {target.name} ({target.stat().st_size:,} bytes)")
