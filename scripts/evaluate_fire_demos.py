"""Run FURG fire clips through the real LH25 pipeline without Telegram delivery.

Only use this for internal demo curation. A completed job or a fire alert alone
does not establish that a clip is a good demonstration; inspect evidence first.
"""

import argparse
import hashlib
import json
import uuid
from pathlib import Path

from schoolguard.config import Settings
from schoolguard.db import Database, now
from schoolguard.schemas import JobRequest
from schoolguard.telegram import TelegramNotifier
from schoolguard.worker import Worker


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("names", nargs="*", default=["house1", "house2", "house4", "house5"])
    parser.add_argument("--apply", action="store_true", help="Create and process local LH25 jobs")
    args = parser.parse_args()
    settings = Settings(start_worker=False)
    root = settings.runtime / "event-data" / "furg"
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    entries = {item["video"].removesuffix(".mp4"): item for item in manifest["items"]}
    db = Database(settings.runtime / "schoolguard.sqlite3")
    admin = db.one("SELECT id FROM users WHERE username='admin' AND role='admin'")
    if not admin:
        raise RuntimeError("Local admin account is required for demo jobs")

    for stem in args.names:
        entry = entries.get(stem)
        if not entry or entry["label"] != "fire" or entry["license"] != "CC0 1.0":
            raise ValueError(f"Not a licensed positive FURG fire clip: {stem}")
        video = (root / entry["video"]).resolve()
        if not video.is_file() or hashlib.sha256(video.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Missing or checksum-mismatched clip: {stem}")
        source = db.one("SELECT id,path FROM sources WHERE id=?", ("furg-" + stem,))
        if not source or Path(source["path"]).resolve() != video:
            raise ValueError(f"LH25 source does not match manifest: {stem}")
        config = JobRequest(source_id=source["id"], camera_name="FURG " + stem,
                            model="yolov8n", stride=2, max_seconds=0,
                            detect_fire=True, expected_people=None)
        prior = db.one("SELECT id,config FROM jobs WHERE source_id=? AND status='completed' "
                       "ORDER BY finished_at DESC LIMIT 1", (source["id"],))
        if prior and json.loads(prior["config"]) == config.model_dump():
            print(f"SKIP {stem}: completed job {prior['id']}", flush=True)
            continue
        print(f"{'RUN' if args.apply else 'DRY RUN'} {stem}: sha256 verified", flush=True)
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
        print(f"DONE {stem}: {result['status']}, alerts={counts}, error={result['error']}", flush=True)


if __name__ == "__main__":
    main()
