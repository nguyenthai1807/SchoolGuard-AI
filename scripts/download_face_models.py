"""Download the two data-only OpenCV Zoo face models to the local models folder."""

import hashlib
import json

import cv2
import requests

from schoolguard.config import Settings


REVISION = "47534e27c9851bb1128ccc0102f1145e27f23f98"
MODELS = {
    "face_detection_yunet_2026may.onnx": (
        "face_detection_yunet", 5 * 1024 * 1024,
        "ebafce4e3c118d6554634be5c27ab333b4c047a9a8c3faf1d7cf93101c22f0f0",
    ),
    "face_recognition_sface_2021dec.onnx": (
        "face_recognition_sface", 100 * 1024 * 1024,
        "0ba9fbfa01b5270c96627c4ef784da859931e02f04419c829e83484087c34e79",
    ),
}


def download(url, target, limit, expected):
    if target.is_file() and target.stat().st_size > 100_000:
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected:
            raise ValueError(f"Face model checksum mismatch: {target.name}")
        return actual
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(".download")
    digest = hashlib.sha256()
    size = 0
    try:
        with requests.get(url, stream=True, timeout=(20, 90)) as response:
            response.raise_for_status()
            with temp.open("wb") as output:
                for block in response.iter_content(1024 * 1024):
                    size += len(block)
                    if size > limit:
                        raise ValueError(f"Face model exceeds {limit} bytes: {url}")
                    digest.update(block)
                    output.write(block)
        if size < 100_000:
            raise ValueError("Downloaded a Git LFS pointer or incomplete model, not ONNX data")
        if digest.hexdigest() != expected:
            raise ValueError(f"Face model checksum mismatch: {target.name}")
        temp.replace(target)
    finally:
        temp.unlink(missing_ok=True)
    return digest.hexdigest()


def main():
    settings = Settings()
    checksums = {}
    for filename, (folder, limit, expected) in MODELS.items():
        url = ("https://media.githubusercontent.com/media/opencv/opencv_zoo/"
               f"{REVISION}/models/{folder}/{filename}")
        checksums[filename] = download(url, settings.models / filename, limit, expected)

    detector = cv2.FaceDetectorYN.create(
        str(settings.models / "face_detection_yunet_2026may.onnx"), "", (320, 320)
    )
    recognizer = cv2.FaceRecognizerSF.create(
        str(settings.models / "face_recognition_sface_2021dec.onnx"), ""
    )
    if detector is None or recognizer is None:
        raise RuntimeError("OpenCV could not load the face models")
    print(json.dumps({"source": "https://github.com/opencv/opencv_zoo",
                      "revision": REVISION, "sha256": checksums}, indent=2))


if __name__ == "__main__":
    main()
