"""Pinned, data-only ONNX model. No downloaded Python code or pickle loading."""

import json

import cv2
import numpy as np

from schoolguard.config import Settings
from scripts.prepare_event_data import download


def main():
    root = Settings().models
    revision = "343990e42d99a5d27e9f35fc7c80880dc5f43f45"
    base = f"https://huggingface.co/fiacecson20/cctv-ai-fire-smoke/resolve/{revision}/"
    target = root / "fire-smoke-v1.onnx"
    checksum = download(base + "best.onnx", target, 30 * 1024 * 1024)
    net = cv2.dnn.readNetFromONNX(str(target))
    net.setInput(np.zeros((1, 3, 320, 320), dtype=np.float32))
    shape = list(net.forward().shape)
    if shape != [1, 6, 2100]:
        raise ValueError(f"Unexpected two-class YOLOv8 output: {shape}")
    download(base + "README.md", root / "fire-smoke-MODEL-CARD.md")
    metadata = {
        "source": "https://huggingface.co/fiacecson20/cctv-ai-fire-smoke",
        "revision": revision,
        "sha256": checksum,
        "input_size": 320,
        "classes": ["fire", "smoke"],
        "output_shape": shape,
        "status": "experimental-pretrained-not-campus-validated",
        "license_note": "Uploader declares MIT weights; source dataset CC-BY 4.0; Ultralytics base AGPL-3.0. Review before redistribution/commercial use.",
    }
    (root / "fire-model.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(json.dumps(metadata))


if __name__ == "__main__":
    main()
