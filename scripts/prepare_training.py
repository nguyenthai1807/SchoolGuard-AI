"""Reproducible three-source person dataset; local copies only, originals read-only."""

import hashlib
import json
import zipfile

import cv2
import numpy as np
import requests
import torch
import yaml
from ultralytics import YOLO

from schoolguard.config import ROOT, Settings

SOURCES = {
    "coco128": "https://github.com/ultralytics/assets/releases/download/v0.0.0/coco128.zip",
    "PennFudanPed": "https://www.cis.upenn.edu/~jshi/ped_html/PennFudanPed.zip",
}


def digest(path):
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def split_index(index, count):
    return "train" if index < int(count * 0.7) else ("val" if index < int(count * 0.85) else "test")


def main():
    settings = Settings()
    downloads = settings.runtime / "downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    data = settings.runtime / "training-data"
    if (data / "manifest.json").exists():
        print("Dataset already prepared; using immutable existing manifest.")
        return
    for split in ["train", "val", "test"]:
        (data / "images" / split).mkdir(parents=True, exist_ok=True)
        (data / "labels" / split).mkdir(parents=True, exist_ok=True)
    archives = []
    for name, url in SOURCES.items():
        archive = downloads / (name + ".zip")
        if not archive.exists():
            print("Downloading " + url, flush=True)
            temp = archive.with_suffix(".download")
            with requests.get(url, stream=True, timeout=90) as response:
                response.raise_for_status()
                with temp.open("wb") as stream:
                    for chunk in response.iter_content(1024 * 1024):
                        stream.write(chunk)
            temp.replace(archive)
        archives.append({"source": name, "url": url, "sha256": digest(archive)})
        with zipfile.ZipFile(archive) as package:
            for member in package.infolist():
                target = (downloads / member.filename).resolve()
                if not target.is_relative_to(downloads.resolve()):
                    raise ValueError("Archive contains unsafe member")
            package.extractall(downloads)
    manifest = []
    seen = {}

    def add(name, image, boxes, split, source, quality, origin):
        h, w = image.shape[:2]
        path = data / "images" / split / (name + ".jpg")
        ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
        if not ok:
            raise RuntimeError("JPEG encoding failed")
        checksum = hashlib.sha256(encoded.tobytes()).hexdigest()
        if checksum in seen:
            if seen[checksum] != split:
                raise ValueError("Cross-split duplicate image")
            return
        seen[checksum] = split
        path.write_bytes(encoded.tobytes())
        lines = []
        for x1, y1, x2, y2 in boxes:
            x1, x2 = max(0, float(x1)), min(w, float(x2))
            y1, y2 = max(0, float(y1)), min(h, float(y2))
            if x2 <= x1 or y2 <= y1:
                continue
            lines.append(
                f"0 {(x1 + x2) / (2 * w):.7f} {(y1 + y2) / (2 * h):.7f} {(x2 - x1) / w:.7f} {(y2 - y1) / h:.7f}"
            )
        (data / "labels" / split / (name + ".txt")).write_text("\n".join(lines), encoding="utf-8")
        manifest.append(
            {
                "name": name,
                "split": split,
                "source": source,
                "quality": quality,
                "origin": origin,
                "sha256": checksum,
                "boxes": len(lines),
            }
        )

    coco = downloads / "coco128"
    files = sorted((coco / "images/train2017").glob("*.jpg"))
    # Stable permutation; independent from labels.
    files.sort(key=lambda p: hashlib.sha256(p.name.encode()).hexdigest())
    for i, path in enumerate(files):
        im = cv2.imread(str(path))
        h, w = im.shape[:2]
        boxes = []
        label = coco / "labels/train2017" / path.with_suffix(".txt").name
        for line in label.read_text().splitlines() if label.exists() else []:
            cls, x, y, bw, bh = map(float, line.split())
            if int(cls) == 0:
                boxes.append(
                    [(x - bw / 2) * w, (y - bh / 2) * h, (x + bw / 2) * w, (y + bh / 2) * h]
                )
        add(
            "coco-" + path.stem,
            im,
            boxes,
            split_index(i, len(files)),
            "coco128",
            "original",
            path.name,
        )

    penn = downloads / "PennFudanPed"
    for prefix in ["FudanPed", "PennPed"]:
        files = sorted((penn / "PNGImages").glob(prefix + "*.png"))
        for i, path in enumerate(files):
            im = cv2.imread(str(path))
            mask = cv2.imread(
                str(penn / "PedMasks" / (path.stem + "_mask.png")), cv2.IMREAD_UNCHANGED
            )
            boxes = []
            for ident in np.unique(mask):
                if ident == 0:
                    continue
                ys, xs = np.where(mask == ident)
                boxes.append([int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1])
            add(
                "penn-" + path.stem,
                im,
                boxes,
                split_index(i, len(files)),
                "penn-fudan",
                "instance-mask",
                path.name,
            )

    torch.set_num_threads(4)
    teacher = YOLO(str(settings.models / "yolo11s.pt"))
    manual = json.loads((ROOT / "docs/spotcheck-labels.json").read_text())["samples"]
    manual_scenes = {m["scene"]: m["boxes"] for m in manual}
    train_scenes = [1, 2, 3, 5, 6, 10, 13]
    for scene in train_scenes:
        videos = sorted((settings.data_root / "training/videos").glob(f"{scene:02}_*.avi"))[:5]
        for vi, path in enumerate(videos):
            cap = cv2.VideoCapture(str(path))
            fps = cap.get(cv2.CAP_PROP_FPS)
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            for index in sorted(
                set([min(count - 1, round(fps * 2)), round(count * 0.4), round(count * 0.75)])
            ):
                cap.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, frame = cap.read()
                if not ok:
                    continue
                if vi == 0 and index == round(fps * 2) and scene in manual_scenes:
                    boxes = manual_scenes[scene]
                    quality = "assistant_reviewed"
                else:
                    prediction = teacher.predict(
                        frame,
                        classes=[0],
                        conf=0.35,
                        iou=0.6,
                        imgsz=640,
                        device="cpu",
                        verbose=False,
                    )[0]
                    boxes = prediction.boxes.xyxy.tolist()
                    quality = "pseudo-yolo11s-conf035"
                add(
                    f"shanghai-{path.stem}-{index}",
                    frame,
                    boxes,
                    "train",
                    "shanghaitech",
                    quality,
                    f"{path.name}:frame={index}",
                )
            cap.release()
        print(f"Prepared ShanghaiTech training scene {scene}", flush=True)
    for sample in manual:
        scene = sample["scene"]
        if scene in train_scenes:
            continue
        path = next(
            iter(sorted((settings.data_root / "training/videos").glob(f"{scene:02}_*.avi")))
        )
        cap = cv2.VideoCapture(str(path))
        index = round(cap.get(cv2.CAP_PROP_FPS) * 2)
        cap.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = cap.read()
        cap.release()
        if not ok:
            raise RuntimeError("Missing held-out frame")
        add(
            f"shanghai-{path.stem}-{index}",
            frame,
            sample["boxes"],
            "val" if scene in [4, 7] else "test",
            "shanghaitech",
            "assistant_reviewed",
            f"{path.name}:frame={index}",
        )
    config = {
        "path": str(data.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": {0: "person"},
    }
    (data / "data.yaml").write_text(yaml.safe_dump(config), encoding="utf-8")
    (data / "manifest.json").write_text(
        json.dumps({"archives": archives, "items": manifest}, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                split: {
                    source: sum(x["split"] == split and x["source"] == source for x in manifest)
                    for source in ["coco128", "penn-fudan", "shanghaitech"]
                }
                for split in ["train", "val", "test"]
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
