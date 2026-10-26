"""Record the two visually reviewed AIRTLab weapon false positives.

Dry run by default. --apply changes only the two exact local alert IDs below,
preserves evidence, and writes an audit record for each review.
"""

import argparse
import json
from pathlib import Path

from schoolguard.db import Database, now


REVIEWED = (
    ("c14dbd36b4604b4c85374f031f707b35", "b003804c140b49ed9e7bacc9de7bd89c",
     "Nghi hung khí báo sai: khung AI nằm trên mép cửa tối/người, không thấy vật được khoanh là hung khí."),
    ("7fd34bbe5e6545bda104eee137d5d6ba", "fbae5b588ab24a75954868f5d437cd11",
     "Nghi hung khí báo sai: khung AI nằm trên giày; cây gậy có trong cảnh nhưng không nằm trong khung vật thể AI."),
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--runtime", type=Path, default=Path("runtime"))
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    db = Database(runtime / "schoolguard.sqlite3")
    admin = db.one("SELECT id FROM users WHERE username='admin' AND role='admin'")
    if not admin:
        raise RuntimeError("Local Admin reviewer missing")
    rows = []
    for alert_id, job_id, note in REVIEWED:
        row = db.one("SELECT id,job_id,event_type,status,evidence FROM alerts WHERE id=?", (alert_id,))
        if not row or row["job_id"] != job_id or row["event_type"] != "weapon":
            raise ValueError(f"Alert identity changed: {alert_id}")
        if not (runtime / "jobs" / job_id / row["evidence"]).is_file():
            raise ValueError(f"Evidence file missing: {alert_id}")
        if row["status"] not in ("new", "false_positive"):
            raise ValueError(f"Alert already reviewed differently: {alert_id}")
        rows.append((alert_id, row["status"], note))
    for alert_id, status, _ in rows:
        print(f"{'APPLY' if args.apply else 'DRY RUN'} {alert_id}: {status} -> false_positive")
    if not args.apply:
        return
    with db.connect() as conn:
        for alert_id, status, note in rows:
            if status == "false_positive":
                continue
            cursor = conn.execute(
                "UPDATE alerts SET status='false_positive',note=?,reviewed_by=? "
                "WHERE id=? AND status='new' AND event_type='weapon'",
                (note, admin["id"], alert_id),
            )
            if cursor.rowcount != 1:
                raise RuntimeError(f"Concurrent alert change: {alert_id}")
            conn.execute(
                "INSERT INTO audit(at,user_id,action,target,detail) VALUES(?,?,?,?,?)",
                (now(), admin["id"], "review_alert", alert_id,
                 json.dumps({"status": "false_positive", "note": note}, ensure_ascii=False)),
            )


if __name__ == "__main__":
    main()
