"""Download optional official Ultralytics YOLO26 checkpoints into project models/."""

import argparse
import os
from pathlib import Path

from schoolguard.config import Settings

CHOICES = ("yolo26n", "yolo26s", "yolo26n-pose")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("models", nargs="*", choices=CHOICES)
    args = parser.parse_args()
    from ultralytics import YOLO, __version__

    if tuple(map(int, __version__.split(".")[:3])) < (8, 4, 182):
        raise RuntimeError("YOLO26 cần ultralytics>=8.4.182 trong .venv của dự án.")
    directory = Settings().models.resolve()
    directory.mkdir(parents=True, exist_ok=True)
    original = Path.cwd()
    try:
        os.chdir(directory)
        for name in (args.models or CHOICES):
            path = directory / f"{name}.pt"
            if path.is_file():
                print(f"Already present: {path.name} ({path.stat().st_size:,} bytes)")
                continue
            # Ultralytics resolves official release assets; never fetch from a mirror.
            YOLO(path.name)
            if not path.is_file() or path.stat().st_size < 100_000:
                raise RuntimeError(f"Checkpoint {name} was not downloaded correctly.")
            print(f"Ready: {path.name} ({path.stat().st_size:,} bytes)")
    finally:
        os.chdir(original)


if __name__ == "__main__":
    main()
