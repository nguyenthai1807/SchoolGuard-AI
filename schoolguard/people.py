"""Anonymous per-video track gallery; head crops are not face recognition."""

import json

import cv2


class PeopleGallery:
    MAX_TRACKS = 500

    def __init__(self, directory):
        self.directory = directory
        self.records = {}
        self.truncated = False

    def update(self, frame, detections, timestamp):
        height, width = frame.shape[:2]
        for detection in detections:
            track = detection.get("track_id")
            if track is None:
                continue
            track = int(track)
            if track < 0:
                continue
            record = self.records.get(track)
            if record is None:
                if len(self.records) >= self.MAX_TRACKS:
                    self.truncated = True
                    continue
                record = {"track_id": track, "first_seen": round(timestamp, 2),
                          "seen_count": 0, "image": None, "score": -1.0}
                self.records[track] = record
            record["seen_count"] += 1
            x1, y1, x2, y2 = detection["bbox"]
            left, right = max(0, int(x1 * width)), min(width, int(x2 * width))
            top = max(0, int(y1 * height))
            bottom = min(height, int((y1 + (y2 - y1) * 0.42) * height))
            if right - left < 16 or bottom - top < 16:
                continue
            crop = frame[top:bottom, left:right]
            sample = cv2.resize(crop, (160, 160), interpolation=cv2.INTER_AREA)
            gray = cv2.cvtColor(sample, cv2.COLOR_BGR2GRAY)
            score = min((right - left) * (bottom - top), 80000) * (
                1 + min(float(cv2.Laplacian(gray, cv2.CV_64F).var()), 300) / 300
            )
            if score <= record["score"] * 1.1:
                continue
            ok, data = cv2.imencode(".jpg", sample, [cv2.IMWRITE_JPEG_QUALITY, 85])
            if ok:
                filename = f"person-{track}.jpg"
                (self.directory / filename).write_bytes(data.tobytes())
                record["image"] = filename
                record["score"] = score

    def finish(self):
        items = [
            {key: value for key, value in record.items() if key != "score"}
            for record in sorted(self.records.values(), key=lambda row: row["first_seen"])
        ]
        payload = {"items": items, "count": len(items), "truncated": self.truncated,
                   "count_is_tracks_not_unique_identities": True}
        (self.directory / "people.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
        return payload
