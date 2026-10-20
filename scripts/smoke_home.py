"""Run the real LH25 video pipeline on one local clip without a web login.

Artifacts stay under runtime/smoke-runs. This is a development smoke test,
not a measured validation set or a claim of sensitivity/specificity.
"""

import argparse
import json
import uuid
from pathlib import Path

from schoolguard.auth import bootstrap
from schoolguard.config import ROOT, Settings
from schoolguard.db import Database, now
from schoolguard.schemas import JobRequest
from schoolguard.telegram import TelegramNotifier
from schoolguard.worker import Worker


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("video", type=Path)
    parser.add_argument("--seconds", type=float, default=0)
    parser.add_argument("--fire", action="store_true")
    parser.add_argument("--falls", action="store_true")
    parser.add_argument("--faces", action="store_true")
    parser.add_argument("--expected-people", type=int, default=1)
    args = parser.parse_args()
    video = args.video.resolve()
    if not video.is_file() or video.suffix.lower() not in {".mp4", ".avi", ".mov", ".mkv"}:
        parser.error("Choose an existing video file.")
    settings = Settings(runtime=ROOT / "runtime" / "smoke-runs", models=ROOT / "models",
                        start_worker=False)
    settings.runtime.mkdir(parents=True, exist_ok=True)
    db = Database(settings.runtime / "schoolguard.sqlite3")
    bootstrap(db, settings.runtime)
    user_id = db.one("SELECT id FROM users WHERE username='admin'")["id"]
    ident = uuid.uuid4().hex
    config = JobRequest(
        source_id=ident, camera_name=video.stem[:80], model="yolo11n-pose",
        detect_falls=args.falls, detect_fire=args.fire, recognize_faces=args.faces,
        expected_people=args.expected_people, max_seconds=args.seconds,
    )
    db.execute("INSERT INTO sources VALUES(?,?,?,?,?)",
               (ident, video.name, str(video), "video", "smoke"))
    db.execute("INSERT INTO jobs(id,source_id,status,created_at,config,user_id) "
               "VALUES(?,?,'running',?,?,?)",
               (ident, ident, now(), config.model_dump_json(), user_id))
    worker = Worker(db, settings, notifier=TelegramNotifier(token="", chat_id=""))
    worker.run(db.one("SELECT * FROM jobs WHERE id=?", (ident,)))
    result = db.one("SELECT status,error,summary FROM jobs WHERE id=?", (ident,))
    print(json.dumps({"job_id": ident, "video": video.name, "status": result["status"],
                      "error": result["error"],
                      "summary": json.loads(result["summary"]) if result["summary"] else None},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
