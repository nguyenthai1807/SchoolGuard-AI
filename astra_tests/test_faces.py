"""Face gallery and webcam day grouping with deterministic model outputs."""

import cv2
import numpy as np
import pytest
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
            analyzer = app.state.live_sessions[session_id]["analyzer"]
            analyzer.detector = lambda _frame: [
                {"track_id": 1, "confidence": .9, "bbox": [.05, .05, .4, 1.]},
                {"track_id": 2, "confidence": .9, "bbox": [.55, .05, .9, 1.]},
            ]
            for _ in range(3):
                analyzer.last_face = -10
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
    assert ledger.update(frame, 1.1)["total"] == 1
    assert ledger.update(frame, 2.2)["total"] == 2


def test_live_face_turn_keeps_number_without_corrupting_embedding(tmp_path):
    from schoolguard.faces import FaceLedger

    class MemoryDB:
        def all(self, *_args):
            return []
        def execute(self, *_args):
            pass

    vector = np.array([1., 0.], dtype=np.float32)
    def recognize(_frame):
        return [{"bbox": [.2, .1, .4, .3], "confidence": .95,
                 "embedding": vector.copy(), "image": b"jpeg"}]
    ledger = FaceLedger(MemoryDB(), tmp_path, "live", "test", recognize)
    body = [{"track_id": 1, "bbox": [.1, .05, .6, .95]}]
    for t in range(3):
        ledger.observe_people(body, t)
        result = ledger.update(None, t, people=body)
    assert result["total"] == 1
    number = result["visible"][0]["number"]
    vector[:] = [0., 1.]
    for t in range(3, 9):
        ledger.observe_people(body, t)
        result = ledger.update(None, t, people=body)
        assert result["total"] == 1
        assert result["visible"][0]["number"] == number
    np.testing.assert_array_equal(next(iter(ledger.records.values()))["embedding"], [1., 0.])
    ledger.observe_people([], 12)
    assert ledger.body_faces == {}
    other = [{"track_id": 2, "bbox": [.1, .05, .6, .95]}]
    for t in range(13, 16):
        ledger.observe_people(other, t)
        result = ledger.update(None, t, people=other)
    assert result["total"] == 2


def test_live_face_single_unmatched_sample_is_not_counted(tmp_path):
    from schoolguard.faces import FaceLedger
    class MemoryDB:
        def all(self, *_args):
            return []
        def execute(self, *_args):
            raise AssertionError("Should not save an unconfirmed face")
    def recognize(_frame):
        return [{"bbox": [.2, .1, .4, .3], "confidence": .95,
                 "embedding": np.array([1., 0.]), "image": b"jpeg"}]
    ledger = FaceLedger(MemoryDB(), tmp_path, "live", "test", recognize)
    assert ledger.update(None, 0, people=[])['total'] == 0
    ledger.pending_faces.clear()
    assert ledger.update(None, 1, people=[{"track_id": 1, "bbox": [0, 0, 1, 1]}])['total'] == 0


def test_delete_face_routes_remove_only_selected_live_data(tmp_path):
    from fastapi import HTTPException
    import pytest
    settings = Settings(runtime=tmp_path / "runtime", models=tmp_path / "models",
                        data_root=tmp_path / "data", start_worker=False)
    app = create_app(settings, detector_factory=NoPeople)
    db = app.state.db
    db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'tester','unused','admin')")
    db.execute("INSERT INTO sources VALUES('s','test','x','live','live')")
    db.execute("INSERT INTO jobs(id,source_id,status,created_at,config,user_id) VALUES('j','s','running','now','{}',1)")
    folder = settings.runtime / 'faces'
    folder.mkdir()
    for ident, kind in [('a', 'live'), ('b', 'live'), ('c', 'video')]:
        db.execute("INSERT INTO faces VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                   (ident, 'live:2026-10-22', kind, 'j', '2026-10-22', 1,
                    'now', 'now', 0, 1, .9, b'feature', ident+'.jpg'))
        (folder / (ident+'.jpg')).write_bytes(b'jpeg')
    single = next(r.endpoint for r in app.routes if r.path == '/api/faces/{ident}' and 'DELETE' in r.methods)
    daily = next(r.endpoint for r in app.routes if r.path == '/api/faces' and 'DELETE' in r.methods)
    assert single('a', current={'id': 1}) == {'deleted': 1}
    assert not (folder / 'a.jpg').exists()
    assert (folder / 'b.jpg').exists()
    with pytest.raises(HTTPException) as exc:
        single('c', current={'id': 1})
    assert exc.value.status_code == 404
    with pytest.raises(HTTPException) as exc:
        daily('../invalid', current={'id': 1})
    assert exc.value.status_code == 422
    assert daily('2026-10-22', current={'id': 1}) == {'deleted': 1}
    assert (folder / 'c.jpg').exists()
    assert daily('2026-10-22', current={'id': 1}) == {'deleted': 0}


def test_closeup_face_saves_without_body_and_survives_slow_frames(tmp_path):
    from schoolguard.faces import FaceLedger
    class MemoryDB:
        def all(self, *_args): return []
        def execute(self, *_args): pass
    def recognize(_frame):
        return [{"bbox": [.2, .1, .6, .5], "confidence": .95,
                 "embedding": np.array([1., 0.], dtype=np.float32), "image": b"jpeg"}]
    ledger = FaceLedger(MemoryDB(), tmp_path, "live", "test", recognize)
    for t in (0, 4, 8):
        ledger.observe_people([], t)
        result = ledger.update(None, t, people=[])
    assert result['total'] == 1
    assert result['visible'][0]['number'] == 1
    assert not result['visible'][0].get('pending')


def test_clear_faces_confirm_in_two_samples_but_weak_faces_need_three(tmp_path):
    from schoolguard.faces import FaceLedger
    class MemoryDB:
        def all(self, *_args): return []
        def execute(self, *_args): pass
    confidence = .95
    def recognize(_frame):
        return [{"bbox": [.2, .1, .6, .5], "confidence": confidence,
                 "embedding": np.array([1., 0.], dtype=np.float32), "image": b"jpeg"}]
    ledger = FaceLedger(MemoryDB(), tmp_path, "live", "test", recognize)
    assert ledger.update(None, 0, people=[])['total'] == 0
    assert ledger.update(None, .4, people=[])['total'] == 1
    confidence = .75
    ledger = FaceLedger(MemoryDB(), tmp_path, "live", "test", recognize)
    assert ledger.update(None, 0, people=[])['total'] == 0
    assert ledger.update(None, .4, people=[])['total'] == 0
    assert ledger.update(None, .8, people=[])['total'] == 1


def test_recognizer_keeps_720p_detail_and_both_small_faces():
    from schoolguard.faces import FaceRecognizer
    class Detector:
        def setInputSize(self, size):
            assert size == (1280, 720)
        def detect(self, _image):
            rows = np.zeros((2, 15), dtype=np.float32)
            rows[0, :4] = [100, 100, 25, 26]
            rows[1, :4] = [800, 100, 28, 28]
            rows[:, 14] = .9
            return None, rows
    class Recognizer:
        def alignCrop(self, _image, _face): return np.zeros((112, 112, 3), dtype=np.uint8)
        def feature(self, _image): return np.array([1., 0.], dtype=np.float32)
    recognizer = object.__new__(FaceRecognizer)
    recognizer.detector, recognizer.recognizer = Detector(), Recognizer()
    result = recognizer(np.zeros((720, 1280, 3), dtype=np.uint8))
    assert len(result) == 2
    assert result[0]['bbox'][0] == 100/1280


def test_face_retry_targets_missing_person_and_maps_coordinates():
    from schoolguard.faces import FaceRecognizer
    recognizer = object.__new__(FaceRecognizer)
    calls = []
    first = {'bbox': [.1, .1, .3, .25], 'confidence': .95, 'embedding': np.array([1., 0.]), 'image': b'a'}
    def detect(frame, max_side=1280):
        calls.append((frame.shape, max_side))
        if len(calls) == 1: return [first]
        return [{'bbox': [.2, .1, .8, .4], 'confidence': .9, 'embedding': np.array([0., 1.]), 'image': b'b'}]
    recognizer._detect = detect
    people = [{'bbox': [.05, .05, .4, .95]}, {'bbox': [.6, .1, .9, .9]}]
    faces = recognizer(np.zeros((1000, 1000, 3), dtype=np.uint8), people=people)
    assert len(calls) == 2  # first person already has a face
    assert calls[1] == ((440, 300, 3), 640)
    assert len(faces) == 2
    assert faces[1]['bbox'] == pytest.approx([.66, .144, .84, .276])
