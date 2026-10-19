"""Download a bounded research starter set from authors, not unlicensed mirrors.

Media stays ignored in runtime/event-data; no private video is uploaded.
"""

import hashlib
import json
import subprocess

import cv2
import imageio_ffmpeg
import requests

from schoolguard.config import Settings
from schoolguard.db import Database

AIRTLAB = "https://raw.githubusercontent.com/airtlab/A-Dataset-for-Automatic-Violence-Detection-in-Videos/1f7747e104301ccaa82ef5a2f6804b51ced1c398/"
FIRE = "https://raw.githubusercontent.com/pedbrgs/Fire-Detection/9d99b0e71fd4cc930da053a41b79de1c58aabdf2/"


def download(url, target, max_bytes=100 * 1024 * 1024):
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        return hashlib.sha256(target.read_bytes()).hexdigest()
    temp = target.with_suffix(target.suffix + ".partial")
    total = 0
    with requests.get(url, stream=True, timeout=(20, 45)) as response:
        response.raise_for_status()
        with temp.open("wb") as output:
            for chunk in response.iter_content(1024 * 1024):
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("Download exceeds bounded starter-set limit")
                output.write(chunk)
    temp.replace(target)
    return hashlib.sha256(target.read_bytes()).hexdigest()


def main():
    settings = Settings()
    root = settings.runtime / "event-data"
    root.mkdir(parents=True, exist_ok=True)
    db = Database(settings.runtime / "schoolguard.sqlite3")
    manifest = {
        "version": 1,
        "items": [],
        "failures": [],
        "limitations": [
            "Starter set only, not evidence of trained action accuracy.",
            "AIRTLab clips are staged by actors. Different views of one action must share a split.",
            "Fire frames have no bounding boxes; require human annotation before supervised detection training.",
            "Do not randomly split adjacent frames. Additional camera/subject-independent holdout is required.",
            "RWF-2000 not downloaded: original authors withdrew public video distribution for privacy reasons.",
        ],
    }
    items = []
    for category in ("violent", "non-violent"):
        for number in range(1, 7):
            items.append(
                {
                    "url": AIRTLAB + f"violence-detection-dataset/{category}/cam1/{number}.mp4",
                    "file": f"airtlab/{category}-{number:03}.mp4",
                    "source": "AIRTLab",
                    "label": category,
                    "split": "train" if number <= 4 else "val" if number == 5 else "test",
                    "group": f"airtlab-{category}-{number}",
                    "label_quality": "author_clip_label",
                    "license": "Research and educational use; Bianculli et al. 2020, doi:10.1016/j.dib.2020.106587",
                }
            )
    items.append(
        {
            "url": FIRE + "examples/wildfire.mp4",
            "file": "fire/wildfire.mp4",
            "source": "Fire-Detection author example",
            "label": "fire-smoke-example",
            "split": "annotation-pool",
            "group": "wildfire-author-example",
            "label_quality": "requires_frame_annotation",
            "license": "Author repository example; MIT repo; Venancio et al. 2023. No redistribution by this project.",
        }
    )
    for category in ("fall", "adl"):
        for number in range(1, 4):
            items.append(
                {
                    "url": f"http://fenix.ur.edu.pl/~mkepski/ds/data/{category}-{number:02}-cam0.mp4",
                    "file": f"urfd/{category}-{number:02}-cam0.mp4",
                    "source": "UR Fall Detection",
                    "label": category,
                    "split": ("train", "val", "test")[number - 1],
                    "group": f"urfd-{category}-{number:02}",
                    "label_quality": "author_clip_label",
                    "license": "CC BY-NC-SA 4.0; non-commercial academic use; Kwolek and Kepski 2014. Preview video; exact sensor timestamps available separately.",
                }
            )
    for item in items:
        try:
            path = root / item["file"]
            item["sha256"] = download(item["url"], path)
            if item["source"] == "UR Fall Detection":
                # Author MP4 previews contain depth (left) + RGB (right).
                # Preserve originals and derive only the RGB half for inference.
                rgb = path.with_name(path.stem + "-rgb.mp4")
                if not rgb.is_file():
                    partial = rgb.with_suffix(".partial.mp4")
                    subprocess.run(
                        [
                            imageio_ffmpeg.get_ffmpeg_exe(),
                            "-y",
                            "-loglevel",
                            "error",
                            "-i",
                            str(path),
                            "-vf",
                            "crop=iw/2:ih:iw/2:0",
                            "-an",
                            "-c:v",
                            "libx264",
                            "-pix_fmt",
                            "yuv420p",
                            "-movflags",
                            "+faststart",
                            str(partial),
                        ],
                        check=True,
                        timeout=60,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                    )
                    partial.replace(rgb)
                item["derived_file"] = str(rgb.relative_to(root))
                item["derived_sha256"] = hashlib.sha256(rgb.read_bytes()).hexdigest()
                item["transformation"] = (
                    "RGB right-half crop of author depth+RGB preview, H264; timestamps follow preview FPS"
                )
                path = rgb
            capture = cv2.VideoCapture(str(path))
            if not capture.isOpened():
                raise ValueError("Downloaded media cannot be decoded")
            fps, count = capture.get(cv2.CAP_PROP_FPS), int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
            if fps <= 0 or count <= 0:
                raise ValueError("Invalid video metadata")
            item.update(fps=fps, frames=count, duration=count / fps)
            # Three selected frames, grouped with the clip; no invented frame labels.
            images = []
            for index in sorted({int(count * f) for f in (0.2, 0.5, 0.8)}):
                capture.set(cv2.CAP_PROP_POS_FRAMES, index)
                ok, image = capture.read()
                if not ok:
                    raise ValueError("Failed to extract frame")
                output = path.with_name(path.stem + f"-frame-{index}.jpg")
                if not cv2.imwrite(str(output), image):
                    raise ValueError("Failed to write frame")
                images.append(str(output.relative_to(root)))
            capture.release()
            item["images"] = images
            manifest["items"].append(item)
            ident = hashlib.sha256(item["file"].encode()).hexdigest()[:24]
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,path=excluded.path,kind=excluded.kind,split=excluded.split",
                (ident, "[research] " + path.stem, str(path.resolve()), "video", "research"),
            )
            print("Prepared " + item["file"], flush=True)
        except Exception as exc:
            manifest["failures"].append({"file": item["file"], "error": str(exc)})
            print("Unavailable " + item["file"] + ": " + str(exc), flush=True)
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    for url, name in [
        (AIRTLAB + "readme.md", "AIRTLab-README.md"),
        (FIRE + "LICENSE", "fire-example-LICENSE.txt"),
    ]:
        try:
            download(url, root / "provenance" / name)
        except requests.RequestException as exc:
            print("Provenance unavailable: " + str(exc))
    print(json.dumps({"prepared": len(manifest["items"]), "failed": len(manifest["failures"])}))


if __name__ == "__main__":
    main()
