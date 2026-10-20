"""Face gallery and webcam day grouping with deterministic model outputs."""

import cv2
import numpy as np
from fastapi.testclient import TestClient

from schoolguard.app import create_app
from schoolguard.config import Settings
from schoolguard.worker import Worker


class NoPeople:
    device = "test"

    def __init__(self, settings, config):
        pass

    def __call__(self, frame):
        return []


class TwoFaces:
    def __init__(self, settings):
        pass

    def __call__(self, frame):
        ok, image = cv2.imencode(".jpg", frame)
        assert ok
        return [
            {"bbox": [0.1, 0.1, 0.3, 0.4], "confidence": 0.95,
             "embedding": np.array([1.0, 0.0], dtype=np.float32),
             "image": image.tobytes()},
            {"bbox": [0.6, 0.1, 0.8, 0.4], "confidence": 0.94,
             "embedding": np.array([0.0, 1.0], dtype=np.float32),
             "image": image.tobytes()},
        ]


def test_video_gallery_and_webcam_daily_dedup(tmp_path, monkeypatch):
    monkeypatch.delenv("LH25_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SCHOOLGUARD_ADMIN_PASSWORD", raising=False)
    root = tmp_path / "data" / "training" / "videos"
    root.mkdir(parents=True)
    writer = cv2.VideoWriter(str(root / "sample.avi"),
                             cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    assert writer.isOpened()
    image = np.zeros((120, 160, 3), dtype=np.uint8)
    for _ in range(12):
        writer.write(image)
    writer.release()
    ok, encoded = cv2.imencode(".jpg", image)
    assert ok
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo11s.pt").write_bytes(b"stub")
    (models / "yolo11n-pose.pt").write_bytes(b"stub")
    settings = Settings(data_root=tmp_path / "data", runtime=tmp_path / "runtime",
                        models=models, start_worker=False)
    app = create_app(settings, detector_factory=NoPeople, face_factory=TwoFaces)

    with TestClient(app) as client:
        assert client.get("/api/faces/days").status_code == 401
        password = (settings.runtime / "admin-password.txt").read_text()
        assert client.post("/api/login", json={"username": "admin", "password": password}).status_code == 200

        source = client.get("/api/sources?split=training").json()["items"][0]
        created = client.post("/api/jobs", json={"source_id": source["id"],
                                                 "recognize_faces": True, "max_seconds": 0})
        assert created.status_code == 202
        ident = created.json()["id"]
        job = app.state.db.one("SELECT * FROM jobs WHERE id=?", (ident,))
        Worker(app.state.db, settings, detector_factory=NoPeople,
               face_factory=TwoFaces).run(job)
        finished = client.get(f"/api/jobs/{ident}").json()
        assert finished["status"] == "completed", finished["error"]
        assert finished["summary"]["unique_faces"] == 2
        gallery = client.get(f"/api/faces?job_id={ident}").json()
        assert gallery["total"] == 2
        assert [face["ordinal"] for face in gallery["items"]] == [1, 2]
        assert all(face["seen_count"] >= 2 for face in gallery["items"])
        assert "embedding" not in gallery["items"][0]
        assert client.get(f"/api/faces/{gallery['items'][0]['id']}/image").headers[
            "content-type"] == "image/jpeg"

        payload = {"source_id": "live", "model": "yolo11n-pose", "recognize_faces": True}
        for day in ("2026-10-20", "2026-10-20", "2026-10-21"):
            response = client.post("/api/live/start", json=payload)
            assert response.status_code == 201
            session_id = response.json()["id"]
            app.state.live_sessions[session_id]["analyzer"].face_ledger.day_provider = lambda d=day: d
            result = client.post(f"/api/live/{session_id}/frame",
                                 files={"file": ("frame.jpg", encoded.tobytes(), "image/jpeg")})
            assert result.status_code == 200, result.text
            assert result.json()["face_count_today"] == 2
            assert len(result.json()["faces"]) == 2
            assert client.post(f"/api/live/{session_id}/stop").status_code == 200

        days = client.get("/api/faces/days").json()["items"]
        assert {entry["day"]: entry["count"] for entry in days} == {
            "2026-10-20": 2, "2026-10-21": 2,
        }
        assert client.get("/api/faces?day=2026-10-20").json()["total"] == 2
        assert client.get("/api/faces?day=2026-10-21").json()["total"] == 2
        assert client.get("/api/faces?day=bad").status_code == 422
        assert client.get("/api/faces").status_code == 422


def test_face_capture_conflicts_with_redaction():
    from pydantic import ValidationError

    from schoolguard.schemas import JobRequest

    try:
        JobRequest(source_id="video", recognize_faces=True, redact=True)
    except ValidationError:
        pass
    else:
        raise AssertionError("redacted jobs must not store unblurred face crops")


def test_tiny_face_stays_one_person_when_embedding_changes_between_frames(tmp_path):
    from schoolguard.db import Database, now
    from schoolguard.faces import FaceLedger

    samples = [
        ([0.45, 0.1, 0.51, 0.2], [1.0, 0.0]),
        ([0.47, 0.1, 0.53, 0.2], [0.38, 0.925]),
        ([0.8, 0.1, 0.86, 0.2], [-0.5, 0.866]),
    ]

    def recognize(_frame):
        box, vector = samples.pop(0)
        feature = np.array(vector, dtype=np.float32)
        feature /= np.linalg.norm(feature)
        return [{"bbox": box, "confidence": 0.91,
                 "embedding": feature, "image": b"jpeg"}]

    db = Database(tmp_path / "faces.sqlite3")
    db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'test','test','admin')")
    db.execute("INSERT INTO sources(id,name,path,kind,split) VALUES('source','test','x','video','test')")
    db.execute("INSERT INTO jobs(id,source_id,status,created_at,config,user_id) "
               "VALUES('test-video','source','running',?,'{}',1)", (now(),))
    ledger = FaceLedger(db, tmp_path, "video", "test-video", recognize)
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    assert ledger.update(frame, 0.0)["total"] == 1
    assert ledger.update(frame, 0.5)["total"] == 1
    assert ledger.update(frame, 1.0)["total"] == 2
