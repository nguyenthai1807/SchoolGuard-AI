"""Download a tiny CC0 fire-video evaluation set from the original authors.

This is for development testing only. Do not fit the model on these clips and
then report them as an independent test set.
"""

import json

from schoolguard.config import Settings
from schoolguard.db import Database
from scripts.prepare_event_data import download

REVISION = "6aff09d7baa27425f31d1df685284c26cbffe7af"
BASE = f"https://raw.githubusercontent.com/steffensbola/furg-fire-dataset/{REVISION}/"
CLIPS = {"house3": "fire", "house6": "fire", "non_fire_patrolbot_onboard": "non-fire"}


def main():
    settings = Settings()
    root = settings.runtime / "event-data" / "furg"
    db = Database(settings.runtime / "schoolguard.sqlite3")
    items = []
    for stem, label in CLIPS.items():
        video = root / f"{stem}.mp4"
        annotation = root / f"{stem}.xml"
        video_hash = download(BASE + video.name, video, 25 * 1024 * 1024)
        annotation_hash = download(BASE + annotation.name, annotation, 512 * 1024)
        db.execute("INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?)",
                   ("furg-" + stem, video.name, str(video.resolve()), "video", "research"))
        items.append({"video": video.name, "label": label, "sha256": video_hash,
                      "annotation": annotation.name, "annotation_sha256": annotation_hash,
                      "source": BASE + video.name, "license": "CC0 1.0"})
        print(f"Prepared {video.name}")
    (root / "manifest.json").write_text(
        json.dumps({"revision": REVISION, "license_url": BASE + "LICENSE", "items": items},
                   indent=2), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
