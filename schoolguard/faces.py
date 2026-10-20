"""Local face detection and anonymous matching within one video or camera day."""

import sqlite3
import uuid
from datetime import datetime

import cv2
import numpy as np

from .db import now


FACE_MODELS = ("face_detection_yunet_2026may.onnx", "face_recognition_sface_2021dec.onnx")
MATCH_THRESHOLD = 0.45  # Conservative relative to OpenCV Zoo's 0.363 demo threshold.


def models_ready(settings):
    return all((settings.models / name).is_file() for name in FACE_MODELS)


def local_day():
    return datetime.now().astimezone().date().isoformat()


class FaceRecognizer:
    """YuNet landmarks + SFace embedding; model files never leave this computer."""

    def __init__(self, settings):
        if not models_ready(settings):
            raise FileNotFoundError("Chưa có model khuôn mặt. Chạy python -m scripts.download_face_models.")
        self.detector = cv2.FaceDetectorYN.create(
            str(settings.models / FACE_MODELS[0]), "", (320, 320),
            score_threshold=0.8, nms_threshold=0.3,
        )
        self.recognizer = cv2.FaceRecognizerSF.create(str(settings.models / FACE_MODELS[1]), "")

    def __call__(self, frame):
        height, width = frame.shape[:2]
        scale = min(1.0, 960 / max(width, height))
        sample = cv2.resize(frame, None, fx=scale, fy=scale) if scale < 1 else frame
        self.detector.setInputSize((sample.shape[1], sample.shape[0]))
        _, found = self.detector.detect(sample)
        observations = []
        if found is None:
            return observations
        for raw in found[:30]:
            face = raw.astype(np.float32).copy()
            face[:14] /= scale
            x, y, w, h = face[:4]
            if w < 32 or h < 32:
                continue
            x1, y1 = max(0, int(x)), max(0, int(y))
            x2, y2 = min(width, int(x + w)), min(height, int(y + h))
            if x2 - x1 < 24 or y2 - y1 < 24:
                continue
            aligned = self.recognizer.alignCrop(frame, face)
            feature = self.recognizer.feature(aligned).reshape(-1).astype(np.float32)
            norm = float(np.linalg.norm(feature))
            if not np.isfinite(norm) or norm < 1e-8:
                continue
            feature /= norm
            pad = int(max(w, h) * 0.16)
            crop = frame[max(0, y1-pad):min(height, y2+pad), max(0, x1-pad):min(width, x2+pad)]
            crop = cv2.resize(crop, (160, 160), interpolation=cv2.INTER_AREA)
            ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 88])
            if not ok:
                continue
            observations.append({
                "bbox": [x1 / width, y1 / height, x2 / width, y2 / height],
                "confidence": float(face[14]), "embedding": feature,
                "image": encoded.tobytes(),
            })
        return observations


class FaceLedger:
    """Deduplicate faces per video, or across webcam sessions on the same local day."""

    def __init__(self, db, runtime, kind, job_id, recognizer, day_provider=local_day):
        self.db, self.runtime = db, runtime
        self.kind, self.job_id = kind, job_id
        self.recognizer, self.day_provider = recognizer, day_provider
        self.scope = None
        self.records = {}
        self.refresh_scope()

    def refresh_scope(self):
        day = self.day_provider()
        scope = f"live:{day}" if self.kind == "live" else f"video:{self.job_id}"
        if scope == self.scope:
            return
        self.scope, self.day = scope, day
        self.records = {}
        for row in self.db.all("SELECT id,ordinal,embedding,seen_count FROM faces WHERE scope=?",
                               (scope,)):
            feature = np.frombuffer(row["embedding"], dtype=np.float32).copy()
            if feature.size and np.isfinite(feature).all():
                self.records[row["id"]] = {
                    "ordinal": row["ordinal"], "embedding": feature,
                    "seen_count": row["seen_count"],
                }

    def update(self, frame, video_time):
        self.refresh_scope()
        observations = self.recognizer(frame)
        assigned = set()
        visible = []
        for item in observations:
            candidates = [
                (float(np.dot(item["embedding"], row["embedding"])), ident)
                for ident, row in self.records.items() if ident not in assigned
                and row["embedding"].shape == item["embedding"].shape
            ]
            score, ident = max(candidates, default=(-1.0, None))
            if score < MATCH_THRESHOLD:
                ident = uuid.uuid4().hex
                ordinal = max((r["ordinal"] for r in self.records.values()), default=0) + 1
                filename = ident + ".jpg"
                folder = self.runtime / "faces"
                folder.mkdir(parents=True, exist_ok=True)
                (folder / filename).write_bytes(item["image"])
                self.db.execute(
                    "INSERT INTO faces(id,scope,kind,job_id,day,ordinal,first_seen,last_seen,"
                    "video_time,seen_count,confidence,embedding,image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (ident, self.scope, self.kind, self.job_id, self.day, ordinal,
                     now(), now(), video_time, 1, item["confidence"],
                     sqlite3.Binary(item["embedding"].tobytes()), filename),
                )
                self.records[ident] = {"ordinal": ordinal,
                                       "embedding": item["embedding"].copy(), "seen_count": 1}
            else:
                record = self.records[ident]
                weight = min(record["seen_count"], 20)
                averaged = (record["embedding"] * weight + item["embedding"]) / (weight + 1)
                averaged /= max(float(np.linalg.norm(averaged)), 1e-8)
                record["embedding"] = averaged
                record["seen_count"] += 1
                self.db.execute(
                    "UPDATE faces SET last_seen=?,seen_count=?,embedding=? WHERE id=?",
                    (now(), record["seen_count"], sqlite3.Binary(averaged.tobytes()), ident),
                )
            assigned.add(ident)
            visible.append({"id": ident, "number": self.records[ident]["ordinal"],
                            "bbox": item["bbox"], "confidence": item["confidence"]})
        return {"visible": visible, "total": len(self.records), "day": self.day}


def draw_faces(image, faces):
    height, width = image.shape[:2]
    for face in faces:
        x1, y1, x2, y2 = face["bbox"]
        left, top = int(x1 * width), int(y1 * height)
        right, bottom = int(x2 * width), int(y2 * height)
        cv2.rectangle(image, (left, top), (right, bottom), (164, 228, 156), 2)
        cv2.putText(image, f"FACE {face['number']}", (left, max(18, top-5)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.48, (164, 228, 156), 1, cv2.LINE_AA)
