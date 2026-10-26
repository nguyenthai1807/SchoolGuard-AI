"""Star visually reviewed, research-only LH25 demos for Admin presentations.

No media is copied or uploaded. Never use these clips in STORE advertising.
Dry-run by default; --apply only after reading the evidence review document.
"""

import argparse
import hashlib
import json
from pathlib import Path

from schoolguard.db import Database, now


# (source stem, capability, completed job, evidence timestamp/crop, review note)
REVIEWED = [
    ("fall-01-cam0-rgb", "fall", "a47f15dbd17243d8a053d49b04dc2a99", 3.67,
     "3,67s: người đã ngã xuống sàn; khung pose/cảnh báo trùng người nằm. Nguồn URFD dàn dựng, không chứng minh độ nhạy trong nhà thật."),
    ("fall-02-cam0-rgb", "fall", "753ba5678346471a842027a5ef1220a1", 2.13,
     "2,13s: người ở sát sàn sau cú ngã, khung cảnh báo đặt đúng vùng. Chỉ là clip nghiên cứu dàn dựng."),
    ("fall-03-cam0-rgb", "fall", "6b03a8a53e8f4d6e9374ab575ad261fa", 6.10,
     "6,10s: người nằm trên sàn sau cú ngã, cảnh báo pose tương ứng. Chỉ là clip nghiên cứu dàn dựng."),
    ("fall-04-cam0-rgb", "fall", "67cdc241fed04509a4a348debb29e974", 1.40,
     "1,40s: người đổ sát sàn, cảnh báo khoanh đúng người. Chỉ là clip nghiên cứu dàn dựng."),
    ("fall-05-cam0-rgb", "fall", "bd908a2baf904c48a0837807936660ce", 3.47,
     "3,47s: người ở sát sàn sau cú ngã, cảnh báo khoanh đúng người. Chỉ là clip nghiên cứu dàn dựng."),
    ("non-violent-001", "people", "0b8a6f28cd394e85b13eb911cf5fa669", 3.0,
     "3,00s: có 3 người, model khoanh 2; cảnh báo vượt ngưỡng 1 là đúng nhưng đếm thiếu 1, không dùng để chứng minh đếm chính xác."),
    ("non-violent-002", "people", "44a66b5813c94d97afb56ff3f30af4ce", 3.0,
     "3,00s: 4 người hiện rõ và 4 khung người; cảnh báo vượt mức mặc định 1 là đúng."),
    ("non-violent-003", "people", "ecde14c69cb34d9aaffb97696c3eeb57", 3.0,
     "3,00s: 4 người hiện rõ và 4 khung người; cảnh báo vượt mức mặc định 1 là đúng. Chỉ 2 khuôn mặt nhìn rõ được lưu."),
    ("non-violent-005", "people", "5679ca83e67e48d5802c60a6cb93a5d1", 3.0,
     "3,00s: 4 người hiện rõ và 4 khung người; cảnh báo vượt mức mặc định 1 là đúng. Số crop mặt của cả video có thể bị trùng."),
    ("violent-003", "people", "6ab17300527e4376891552d0471db458", 3.0,
     "3,00s: 4 người hiện rõ và 4 khung người; cảnh báo vượt mức mặc định 1 là đúng. Nhãn violent của bộ dữ liệu không được diễn giải thành cảnh báo xung đột LH25."),
    ("non-violent-001", "face", "0b8a6f28cd394e85b13eb911cf5fa669", "3aa5a9c4bc204f5a92e73a4551191ffe.jpg",
     "Crop mặt người tại 1,00s có mắt/mũi/miệng nhìn được; minh họa lưu mặt, không xác minh danh tính hay mọi người trong clip."),
    ("non-violent-002", "face", "44a66b5813c94d97afb56ff3f30af4ce", "ccac25b1cdb3434098f6ecee719c109c.jpg",
     "Crop mặt nghiêng tại 0,00s thuộc người trong clip; minh họa lưu mặt nghiêng, không xác minh danh tính."),
    ("non-violent-003", "face", "ecde14c69cb34d9aaffb97696c3eeb57", "15a9e40e7aee497d9163ab0ca264a415.jpg",
     "Crop mặt rõ tại 0,00s; video có 4 người nhưng thư viện chỉ lưu 2 mặt. Không nhận mặt người quay lưng."),
    ("non-violent-004", "face", "618174e1f12744219480548d72c26f2e", "06a968aa1e674747a21c90fa2be5600d.jpg",
     "Crop mặt nghiêng tại 0,00s thuộc người trong clip; minh họa lưu mặt, không khẳng định tổng số danh tính."),
    ("violent-003", "face", "6ab17300527e4376891552d0471db458", "5c2f23bf7c0746ca84e1872b47489e33.jpg",
     "Crop mặt nghiêng tại 0,50s thuộc người trong clip; chỉ minh họa gallery lưu mặt, không xác minh danh tính."),
    ("violent-002", "interaction", "b6b3e14b66c64b239bab82efbb6c828d", 1.67,
     "1,67s: cảnh báo chuyển động mạnh trùng cảnh xô đẩy có tiếp xúc; các khung 31/79/126 cho thấy diễn tiến. Dàn dựng; không chứng minh nhận biết mọi xung đột hoặc ý định."),
    ("violent-004", "interaction", "1118d90fc54444eb879fd49595b11cc6", 0.80,
     "0,80s: cảnh báo trong cảnh người cầm gậy tiến tới người ngồi sàn, diễn tiến rõ ở khung 20/51/81. AI không khoanh đúng hung khí; đây chỉ là demo nghi xung đột dàn dựng."),
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--runtime", type=Path, default=Path("runtime"))
    args = parser.parse_args()
    runtime = args.runtime.resolve()
    root = runtime / "event-data"
    initial = json.loads((root / "manifest.json").read_text(encoding="utf-8"))["items"]
    extra_manifest = json.loads((root / "urfd-demo-manifest.json").read_text(encoding="utf-8"))
    extra = extra_manifest["items"]
    entries = {Path(i["file"].replace("\\", "/")).stem: i for i in initial + extra}
    db = Database(runtime / "schoolguard.sqlite3")
    admin = db.one("SELECT id FROM users WHERE username='admin' AND role='admin'")
    if not admin:
        raise RuntimeError("No local Admin account to record reviewer")
    decisions = []
    for stem, capability, job_id, proof, note in REVIEWED:
        origin_stem = stem.removesuffix("-rgb")
        entry = entries[origin_stem]
        license_note = entry.get("license", extra_manifest["license"] if capability == "fall" else "")
        if "non-commercial" not in license_note.lower() and "research and educational" not in license_note.lower():
            raise ValueError(f"Not marked research-only: {stem}")
        original = root / entry["file"].replace("\\", "/")
        if hashlib.sha256(original.read_bytes()).hexdigest() != entry["sha256"]:
            raise ValueError(f"Original SHA mismatch: {stem}")
        relative = entry.get("derived_file", entry["file"]).replace("\\", "/")
        video = (root / relative).resolve()
        if "derived_sha256" in entry and hashlib.sha256(video.read_bytes()).hexdigest() != entry["derived_sha256"]:
            raise ValueError(f"RGB SHA mismatch: {stem}")
        source = db.one("SELECT id FROM sources WHERE name=? AND path=? AND split='research'",
                        ("[research] " + stem, str(video)))
        if not source:
            raise ValueError(f"Research source mismatch: {stem}")
        job = db.one("SELECT id FROM jobs WHERE id=? AND source_id=? AND status='completed'",
                     (job_id, source["id"]))
        if not job:
            raise ValueError(f"Missing completed job: {stem}/{job_id}")
        if capability == "face":
            face = db.one("SELECT 1 FROM faces WHERE job_id=? AND image=?", (job_id, proof))
            if not face or not (runtime / "faces" / proof).is_file():
                raise ValueError(f"Face crop missing: {stem}")
        else:
            event = {"fall": "suspected_fall", "people": "unexpected_person",
                     "interaction": "vigorous_interaction"}[capability]
            alert = db.one(
                "SELECT evidence FROM alerts WHERE job_id=? AND event_type=? "
                "AND status!='false_positive' AND abs(video_time-?)<0.15",
                (job_id, event, proof),
            )
            if not alert or not (runtime / "jobs" / job_id / alert["evidence"]).is_file():
                raise ValueError(f"Reviewed alert missing: {stem}/{capability}")
        rights = ("UR Fall Detection, CC BY-NC-SA 4.0; chỉ dùng demo học thuật nội bộ, "
                  "không dùng trong STORE/quảng cáo; SHA-256 khớp nguồn."
                  if capability == "fall" else
                  "AIRTLab Bianculli et al. 2020; chỉ dùng nghiên cứu/giáo dục nội bộ, "
                  "không dùng trong STORE/quảng cáo; SHA-256 khớp nguồn.")
        decisions.append((source["id"], capability, job_id, rights, note, admin["id"], now(), 1))
    for row in decisions:
        print(f"{'APPLY' if args.apply else 'DRY RUN'} {row[1]} {row[0]} via {row[2]}")
    if args.apply:
        with db.connect() as conn:
            for row in decisions:
                conn.execute(
                    "INSERT OR IGNORE INTO demo_videos(source_id,capability,evidence_job_id,"
                    "rights_note,review_note,reviewed_by,reviewed_at,academic_only) "
                    "VALUES(?,?,?,?,?,?,?,?)", row,
                )
        print([dict(r) for r in db.all("SELECT capability,count(*) AS n FROM demo_videos GROUP BY capability")])


if __name__ == "__main__":
    main()
