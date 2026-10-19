"""Replay saved observations for transparent development error analysis, not blind evaluation."""

import json

from schoolguard.behavior import BehaviorEngine
from schoolguard.config import Settings
from schoolguard.db import Database
from schoolguard.media import Reader
from schoolguard.schemas import JobRequest


def main():
    settings = Settings()
    db = Database(settings.runtime / "schoolguard.sqlite3")
    records = []
    for job in db.all(
        "SELECT j.*,s.name,s.path,s.kind FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.status='completed' ORDER BY j.created_at"
    ):
        config = JobRequest.model_validate_json(job["config"])
        if config.model != "yolo11n-pose":
            continue
        with Reader(job["path"], job["kind"]) as reader:
            engine = BehaviorEngine(
                config, reader.width / reader.height, max(0.5, config.stride / reader.fps * 1.5)
            )
        events = []
        for line in (
            (settings.runtime / "jobs" / job["id"] / "detections.jsonl").read_text().splitlines()
        ):
            row = json.loads(line)
            events.extend(
                {"time": row["time"], "type": a["event_type"], "reason": a["details"].get("reason")}
                for a in engine.update(row["detections"], row["time"])
            )
        records.append({"source": job["name"], "job": job["id"], "events": events})
    (settings.runtime / "event-development-replay.json").write_text(
        json.dumps(records, indent=2), encoding="utf-8"
    )
    print(json.dumps(records, indent=2))


if __name__ == "__main__":
    main()
