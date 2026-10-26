"""Run verified URFD RGB previews through LH25 with Telegram suppressed.

AI alerts still require human review before any demo star is awarded.
"""

import argparse
import hashlib
import json
import uuid

from schoolguard.config import Settings
from schoolguard.db import Database, now
from schoolguard.schemas import JobRequest
from schoolguard.telegram import TelegramNotifier
from schoolguard.worker import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("numbers", nargs="*", type=int, default=[4, 5])
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    settings = Settings(start_worker=False)
    root = settings.runtime / "event-data"
    entries = {item["file"].replace("\\", "/"): item for item in json.loads(
        (root / "urfd-demo-manifest.json").read_text(encoding="utf-8"))["items"]}
    db = Database(settings.runtime / "schoolguard.sqlite3")
    admin = db.one("SELECT id FROM users WHERE username='admin' AND role='admin'")
    if not admin:
        raise RuntimeError("Local Admin account is required")
    for n in args.numbers:
        entry = entries[f"urfd/fall-{n:02}-cam0.mp4"]
        path = (root / entry["derived_file"]).resolve()
        if hashlib.sha256(path.read_bytes()).hexdigest() != entry["derived_sha256"]:
            raise ValueError(f"RGB preview checksum mismatch: {path}")
        source = db.one("SELECT id FROM sources WHERE path=?", (str(path),))
        if not source:
            raise ValueError(f"Source not registered: {path}")
        config = JobRequest(source_id=source["id"], camera_name=f"URFD fall-{n:02}",
                            model="yolo11n-pose", stride=1, max_seconds=0,
                            detect_falls=True, detect_fire=False,
                            detect_interactions=False, recognize_faces=False,
                            expected_people=None)
        print(f"{'RUN' if args.apply else 'DRY RUN'} fall-{n:02}", flush=True)
        if not args.apply:
            continue
        ident = uuid.uuid4().hex
        db.execute("INSERT INTO jobs(id,source_id,status,created_at,config,user_id) "
                   "VALUES(?,?,'running',?,?,?)",
                   (ident, source["id"], now(), config.model_dump_json(), admin["id"]))
        Worker(db, settings, notifier=TelegramNotifier(token="", chat_id="")).run(
            db.one("SELECT * FROM jobs WHERE id=?", (ident,))
        )
        result = db.one("SELECT status,error,summary FROM jobs WHERE id=?", (ident,))
        counts = json.loads(result["summary"])["event_counts"] if result["summary"] else {}
        print(f"DONE fall-{n:02}: {ident}, {result['status']}, {counts}, {result['error']}", flush=True)


if __name__ == "__main__":
    main()
