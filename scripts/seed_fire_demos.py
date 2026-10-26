"""Mark five visually reviewed FURG CC0 fire clips as admin demos.

Run only on an existing local LH25 installation: python -m scripts.seed_fire_demos
Pass --apply after reading the dry-run output. Does not copy or upload media.
"""

import argparse
import hashlib
import json
from pathlib import Path

from schoolguard.db import Database, now


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--runtime", type=Path, default=Path("runtime"))
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    manifest = json.loads((runtime / "event-data/furg/manifest.json").read_text(encoding="utf-8"))
    db = Database(runtime / "schoolguard.sqlite3")
    admin = db.one("SELECT id FROM users WHERE username='admin' AND role='admin'")
    if not admin:
        raise RuntimeError("Không có tài khoản admin cục bộ để ghi lịch sử duyệt.")
    decisions = []
    for name, timestamp, note in (
        ("house1.mp4", 29.36, "Đã xem ảnh bằng chứng tại 29,36s: lửa trong mô hình ngôi nhà thu nhỏ được khoanh đúng. Không đại diện cho nhà thật."),
        ("house3.mp4", 12.51, "Đã xem ảnh bằng chứng tại 12,51s: lửa thật ở cửa sổ mô hình ngôi nhà; cảnh báo fire khoanh đúng vùng."),
        ("house4.mp4", 10.68, "Đã xem ảnh bằng chứng tại 10,68s: lửa trong mô hình ngôi nhà thu nhỏ được khoanh đúng. Không đại diện cho nhà thật."),
        ("house5.mp4", 4.27, "Đã xem ảnh bằng chứng tại 4,27s và 19,75s: lửa trong mô hình ngôi nhà thu nhỏ được khoanh đúng."),
        ("house6.mp4", 28.53, "Đã xem ảnh bằng chứng tại 2,50s (khói) và 28,53s (lửa): cả hai dấu hiệu xuất hiện rõ trong mô hình ngôi nhà."),
    ):
        item = next((item for item in manifest["items"] if item["video"] == name), None)
        if not item or item.get("license") != "CC0 1.0":
            raise RuntimeError(f"Thiếu ghi nhận CC0 cho {name}.")
        file = (runtime / "event-data/furg" / name).resolve()
        if not file.is_file() or hashlib.sha256(file.read_bytes()).hexdigest() != item["sha256"]:
            raise RuntimeError(f"SHA-256 không khớp: {name}.")
        source = db.one("SELECT id,path FROM sources WHERE name=? AND split='research'", (name,))
        if not source or Path(source["path"]).resolve() != file:
            raise RuntimeError(f"Nguồn LH25 không khớp: {name}.")
        job = db.one(
            "SELECT j.id,a.evidence FROM jobs j JOIN alerts a ON a.job_id=j.id "
            "WHERE j.source_id=? AND j.status='completed' AND a.event_type='fire' "
            "AND a.status!='false_positive' AND abs(a.video_time-?)<0.15 "
            "ORDER BY j.finished_at DESC LIMIT 1", (source["id"], timestamp),
        )
        if not job:
            raise RuntimeError(f"Chưa có tác vụ hoàn tất với cảnh báo fire đúng mốc: {name}.")
        if not (runtime / "jobs" / job["id"] / job["evidence"]).is_file():
            raise RuntimeError(f"Thiếu ảnh bằng chứng đã xem: {name}.")
        decisions.append((source["id"], "fire", job["id"],
                          "FURG fire dataset, CC0 1.0; cảnh mô phỏng nhà thu nhỏ, không phải nhà thật; SHA-256 khớp.",
                          note, admin["id"], now()))
    for row in decisions:
        print(f"{'APPLY' if args.apply else 'DRY RUN'}: {row[0]} fire via {row[2]}")
    if args.apply:
        with db.connect() as conn:
            # Upgrade only the two earlier script-created notes; preserve any
            # independent edits made by an admin reviewer.
            conn.execute(
                "UPDATE demo_videos SET rights_note=? WHERE capability='fire' "
                "AND rights_note=? AND source_id IN ('furg-house3','furg-house6')",
                ("FURG fire dataset, CC0 1.0; cảnh mô phỏng nhà thu nhỏ, không phải nhà thật; SHA-256 khớp.",
                 "FURG fire dataset, CC0 1.0; SHA-256 khớp manifest gốc."),
            )
            for row in decisions:
                conn.execute(
                    "INSERT OR IGNORE INTO demo_videos(source_id,capability,evidence_job_id,"
                    "rights_note,review_note,reviewed_by,reviewed_at) VALUES(?,?,?,?,?,?,?)", row
                )
        count = db.one("SELECT count(*) n FROM demo_videos WHERE capability='fire'")["n"]
        print(f"Starred {count} visually reviewed fire clips; other capabilities need eligible, reviewed footage.")


if __name__ == "__main__":
    main()
