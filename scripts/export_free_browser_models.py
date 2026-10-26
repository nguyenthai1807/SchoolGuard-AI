"""Export/validate only the three public Free COCO person checkpoints.

Run explicitly in the project virtualenv after downloading the official .pt files.
This script does not fetch weights, install packages, or publish anything.
"""

from pathlib import Path

import onnx
import onnxruntime as ort
from ultralytics import YOLO


ROOT = Path(__file__).resolve().parents[1]
MODEL_DIR = ROOT / "models"
FREE_MODELS = ("yolov8n", "yolov9t", "yolov10n")


def main() -> None:
    for name in FREE_MODELS:
        checkpoint = MODEL_DIR / f"{name}.pt"
        exported = MODEL_DIR / f"{name}.onnx"
        if not checkpoint.is_file():
            raise RuntimeError(f"Missing official checkpoint: {checkpoint.name}")
        model = YOLO(str(checkpoint))
        if model.task != "detect" or model.names.get(0) != "person":
            raise RuntimeError(f"Not a COCO person detector: {checkpoint.name}")
        if not exported.is_file():
            result = Path(model.export(format="onnx", imgsz=320, opset=12,
                                       dynamic=False, simplify=False))
            if result.resolve() != exported.resolve():
                raise RuntimeError(f"Unexpected export path for {name}: {result}")
        onnx.checker.check_model(onnx.load(str(exported)))
        session = ort.InferenceSession(str(exported), providers=["CPUExecutionProvider"])
        if session.get_inputs()[0].shape != [1, 3, 320, 320] or \
                session.get_outputs()[0].shape != [1, 84, 2100]:
            raise RuntimeError(f"Browser decoder does not support {exported.name}")
        print(f"Ready for browser Free: {exported.name} ({exported.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()
