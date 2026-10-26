"""Run the current dual body/Pose behavior pipeline on selected indexed clips."""

import argparse
import json
import sqlite3

from schoolguard.behavior import BehaviorEngine
from schoolguard.config import Settings
from schoolguard.detector import PersonDetector
from schoolguard.media import Reader
from schoolguard.schemas import JobRequest
from schoolguard.tracking import StableIds, merge_body_and_pose


def find_sources(settings, names):
    with sqlite3.connect(settings.runtime / "schoolguard.sqlite3") as connection:
        connection.row_factory = sqlite3.Row
        return [dict(row) for row in connection.execute("SELECT * FROM sources")
                if row["name"].removeprefix("[research] ").removesuffix(".mp4") in names]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--names", nargs="+", required=True)
    parser.add_argument("--stride", type=int, default=3)
    parser.add_argument("--image-size", type=int, choices=(640, 960), default=640)
    parser.add_argument("--falls", action="store_true")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    settings = Settings(start_worker=False)
    report = []
    for source in find_sources(settings, set(args.names)):
        config = JobRequest(source_id=source["id"], model="yolo11n-pose",
                            image_size=args.image_size, detect_interactions=True,
                            detect_falls=args.falls, lying_seconds=2)
        pose_detector = PersonDetector(settings, config)
        body_detector = PersonDetector(settings, config.model_copy(update={"model": "yolo11s"}))
        identities = StableIds()
        alerts, counts = [], []
        with Reader(source["path"], source["kind"]) as reader:
            engine = BehaviorEngine(config, reader.width / reader.height,
                                    max(.5, args.stride / reader.fps * 1.5))
            for index in range(reader.count):
                frame = reader.read()
                if index % args.stride:
                    continue
                stamp = index / reader.fps
                people = identities.update(
                    merge_body_and_pose(body_detector(frame), pose_detector(frame)), stamp)
                counts.append(len(people))
                alerts.extend(engine.update(people, stamp))
        item = {"name": source["name"].removeprefix("[research] ").removesuffix(".mp4"),
                "stride": args.stride, "peak_people": max(counts, default=0),
                "counts": counts, "alerts": alerts}
        report.append(item)
        print(item["name"], "peak", item["peak_people"],
              "alerts", [(alert["event_type"], round(alert["details"].get("confirmed_timestamp", 0), 2))
                         for alert in alerts], flush=True)
    output = settings.runtime / "regression-20261023" / args.output
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
