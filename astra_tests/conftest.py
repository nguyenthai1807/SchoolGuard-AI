import cv2
import numpy as np
import pytest
from fastapi.testclient import TestClient

from schoolguard.app import create_app
from schoolguard.config import Settings


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("LH25_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SCHOOLGUARD_ADMIN_PASSWORD", raising=False)
    root = tmp_path / "data"
    videos = root / "training/videos"
    videos.mkdir(parents=True)
    path = videos / "01_001.avi"
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"MJPG"), 10, (160, 120))
    assert writer.isOpened()
    for _ in range(20):
        writer.write(np.zeros((120, 160, 3), dtype=np.uint8))
    writer.release()
    frames = root / "testing/frames/01_0001"
    frames.mkdir(parents=True)
    for n in range(5):
        cv2.imwrite(str(frames / f"{n:04}.jpg"), np.zeros((120, 160, 3), dtype=np.uint8))
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo11s.pt").write_bytes(b"test stub; injected detector only")
    return create_app(
        Settings(data_root=root, runtime=tmp_path / "runtime", models=models, start_worker=False)
    )


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        password = (app.state.settings.runtime / "admin-password.txt").read_text()
        assert (
            c.post("/api/login", json={"username": "admin", "password": password}).status_code
            == 200
        )
        yield c


@pytest.fixture
def request_data(client):
    source = client.get("/api/sources?split=training").json()["items"][0]
    return {
        "source_id": source["id"],
        "zones": [{"name": "zone", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}],
        "dwell_seconds": 0.5,
        "max_seconds": 0,
    }


class FakeDetector:
    device = "test"

    def __init__(self, settings, config):
        pass

    def __call__(self, frame):
        return [{"track_id": 1, "confidence": 0.9, "bbox": [0.2, 0.2, 0.4, 0.8]}]


@pytest.fixture
def finished(client, app, request_data):
    from schoolguard.worker import Worker

    row = client.post("/api/jobs", json=request_data).json()
    job = app.state.db.one("SELECT * FROM jobs WHERE id=?", (row["id"],))
    Worker(app.state.db, app.state.settings, FakeDetector).run(job)
    return row["id"]
