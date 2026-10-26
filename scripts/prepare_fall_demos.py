"""Prepare additional official URFD RGB previews for internal academic review.

This is a bounded, non-commercial research-only dataset acquisition. The
original depth+RGB preview is retained; inference uses the derived RGB half.
"""

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import cv2
import imageio_ffmpeg

from scripts.prepare_event_data import download
from schoolguard.config import Settings
from schoolguard.db import Database


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("numbers", nargs="*", type=int, default=[4, 5])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not args.numbers or any(n < 4 or n > 30 for n in args.numbers):
        raise ValueError("Only official URFD fall preview numbers 04-30 are supported")
    root = Settings().runtime / "event-data"
    manifest_path = root / "urfd-demo-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {
        "source": "https://fenix.ur.edu.pl/~mkepski/ds/uf.html",
        "license": "CC BY-NC-SA 4.0; non-commercial academic use only",
        "items": [],
    }
    db = Database(Settings().runtime / "schoolguard.sqlite3") if args.apply else None
    for n in args.numbers:
        stem = f"fall-{n:02}-cam0"
        url = f"http://fenix.ur.edu.pl/~mkepski/ds/data/{stem}.mp4"
        source = root / "urfd" / f"{stem}.mp4"
        rgb = source.with_name(f"{stem}-rgb.mp4")
        print(f"{'APPLY' if args.apply else 'DRY RUN'} {url}", flush=True)
        if not args.apply:
            continue
        digest = download(url, source, max_bytes=20 * 1024 * 1024)
        if not rgb.is_file():
            partial = rgb.with_suffix(".partial.mp4")
            subprocess.run([
                imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                "-i", str(source), "-vf", "crop=iw/2:ih:iw/2:0",
                "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
                "-movflags", "+faststart", str(partial),
            ], check=True, timeout=60, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            partial.replace(rgb)
        cap = cv2.VideoCapture(str(rgb))
        try:
            fps = cap.get(cv2.CAP_PROP_FPS)
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        finally:
            cap.release()
        if fps <= 0 or count <= 0:
            raise ValueError(f"Unusable video: {rgb}")
        entry = {
            "file": source.relative_to(root).as_posix(), "url": url, "sha256": digest,
            "license": "CC BY-NC-SA 4.0; non-commercial academic use only",
            "derived_file": rgb.relative_to(root).as_posix(),
            "derived_sha256": hashlib.sha256(rgb.read_bytes()).hexdigest(),
            "frames": count, "fps": fps, "duration": count / fps,
            "transformation": "RGB right-half crop of original depth+RGB preview",
        }
        manifest["items"] = [i for i in manifest["items"] if i["file"] != entry["file"]] + [entry]
        source_id = hashlib.sha256(entry["file"].encode()).hexdigest()[:24]
        db.execute(
            "INSERT INTO sources(id,name,path,kind,split) VALUES(?,?,?,?,?) "
            "ON CONFLICT(id) DO UPDATE SET name=excluded.name,path=excluded.path,kind=excluded.kind,split=excluded.split",
            (source_id, "[research] " + rgb.stem, str(rgb.resolve()), "video", "research"),
        )
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        print(f"READY {stem}: {count} frames at {fps:.2f} FPS", flush=True)


if __name__ == "__main__":
    main()
