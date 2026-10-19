import cv2
import numpy as np
from fastapi.testclient import TestClient

from schoolguard.app import create_app
from schoolguard.config import Settings
from schoolguard.live import LiveAnalyzer
from schoolguard.schemas import JobRequest
from schoolguard.telegram import TelegramNotifier


def frame():
    ok, encoded = cv2.imencode(".jpg", np.zeros((120, 160, 3), dtype=np.uint8))
    assert ok
    return encoded.tobytes()


class TwoPeople:
    def __init__(self, settings, config):
        pass

    def __call__(self, image):
        return [
            {"track_id": 1, "confidence": 0.9, "bbox": [0.1, 0.1, 0.3, 0.9]},
            {"track_id": 2, "confidence": 0.9, "bbox": [0.6, 0.1, 0.8, 0.9]},
        ]


def test_live_occupancy_sustained_and_not_repeated():
    times = iter([0, 0, 0.5, 1.1, 1.6])
    config = JobRequest(source_id="live", model="yolo11n-pose", expected_people=1,
                        crowd_seconds=1)
    analyzer = LiveAnalyzer(config, TwoPeople(None, None), clock=lambda: next(times))
    results = [analyzer.update(frame()) for _ in range(4)]
    alerts = [a for result in results for a in result["alerts"]]
    assert [a["event_type"] for a in alerts] == ["unexpected_person"]
    assert alerts[0]["details"]["expected"] == 1
    assert alerts[0]["details"]["count"] == 2


def test_telegram_unconfigured_and_success():
    alert = {"event_type": "unexpected_person", "zone": "Vượt mức", "details": {"count": 2}}
    assert TelegramNotifier(token="", chat_id="").send(alert, b"jpg", "Webcam", 2)[1] == "telegram_not_configured"

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    class Session:
        def post(self, url, **kwargs):
            assert url.endswith("/sendPhoto")
            assert kwargs["data"]["chat_id"] == "123"
            assert "2" in kwargs["data"]["caption"]
            return Response()

    assert TelegramNotifier(token="test-token", chat_id="123", session=Session()).send(
        alert, b"jpg", "Webcam", 2
    ) == (True, "delivered")


def test_live_api_creates_evidence_and_stops(tmp_path, monkeypatch):
    monkeypatch.delenv("LH25_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SCHOOLGUARD_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("LH25_TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("LH25_TELEGRAM_CHAT_ID", raising=False)
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo11n-pose.pt").write_bytes(b"injected detector")
    app = create_app(Settings(data_root=tmp_path / "missing", runtime=tmp_path / "runtime",
                              models=models, start_worker=False), detector_factory=TwoPeople)
    with TestClient(app) as client:
        password = (app.state.settings.runtime / "admin-password.txt").read_text()
        assert client.post("/api/login", json={"username": "admin", "password": password}).status_code == 200
        payload = {"source_id": "live", "model": "yolo11n-pose", "expected_people": 1,
                   "crowd_seconds": 1}
        response = client.post("/api/live/start", json=payload)
        assert response.status_code == 201
        ident = response.json()["id"]
        analyzer = app.state.live_sessions[ident]["analyzer"]
        moments = iter([0, 0.5, 1.1])
        analyzer.started = 0
        analyzer.clock = lambda: next(moments)
        for _ in range(3):
            result = client.post(f"/api/live/{ident}/frame",
                                 files={"file": ("frame.jpg", frame(), "image/jpeg")})
            assert result.status_code == 200
        alerts = client.get(f"/api/alerts?job_id={ident}").json()["items"]
        assert len(alerts) == 1
        assert alerts[0]["event_type"] == "unexpected_person"
        assert alerts[0]["telegram_status"] == "telegram_not_configured"
        assert client.post(f"/api/alerts/{alerts[0]['id']}/telegram").status_code == 409
        assert client.get(f"/api/alerts/{alerts[0]['id']}/evidence").status_code == 200
        assert client.post(f"/api/live/{ident}/stop").status_code == 200
        assert client.get(f"/api/jobs/{ident}").json()["status"] == "completed"
        abandoned = client.post("/api/live/start", json=payload).json()["id"]
        assert client.post("/api/live/start", json=payload).status_code == 409
        app.state.live_sessions[abandoned]["last_seen"] = -100
        replacement = client.post("/api/live/start", json=payload)
        assert replacement.status_code == 201
        assert client.get(f"/api/jobs/{abandoned}").json()["status"] == "completed"
        assert client.post(f"/api/live/{replacement.json()['id']}/stop").status_code == 200


def test_failed_telegram_delivery_can_be_retried_once(tmp_path, monkeypatch):
    monkeypatch.delenv("LH25_ADMIN_PASSWORD", raising=False)
    monkeypatch.delenv("SCHOOLGUARD_ADMIN_PASSWORD", raising=False)

    class FakeNotifier:
        configured = True
        calls = 0

        def send(self, alert, evidence, source_name, timestamp):
            self.calls += 1
            assert evidence and source_name == "Webcam test"
            return (False, "telegram_delivery_failed") if self.calls == 1 else (True, "delivered")

    notifier = FakeNotifier()
    monkeypatch.setattr("schoolguard.app.TelegramNotifier", lambda: notifier)
    models = tmp_path / "models"
    models.mkdir()
    (models / "yolo11n-pose.pt").write_bytes(b"injected detector")
    app = create_app(Settings(data_root=tmp_path / "missing", runtime=tmp_path / "runtime",
                              models=models, start_worker=False), detector_factory=TwoPeople)
    with TestClient(app) as client:
        password = (app.state.settings.runtime / "admin-password.txt").read_text()
        assert client.post("/api/login", json={"username": "admin", "password": password}).status_code == 200
        payload = {"source_id": "live", "camera_name": "Webcam test", "model": "yolo11n-pose",
                   "expected_people": 1, "crowd_seconds": 1}
        ident = client.post("/api/live/start", json=payload).json()["id"]
        analyzer = app.state.live_sessions[ident]["analyzer"]
        moments = iter([0, 0.5, 1.1])
        analyzer.started = 0
        analyzer.clock = lambda: next(moments)
        for _ in range(3):
            assert client.post(f"/api/live/{ident}/frame",
                               files={"file": ("frame.jpg", frame(), "image/jpeg")}).status_code == 200
        alert = client.get(f"/api/alerts?job_id={ident}").json()["items"][0]
        assert alert["telegram_status"] == "telegram_delivery_failed"
        assert client.post(f"/api/live/{ident}/stop").status_code == 200
        retry = client.post(f"/api/alerts/{alert['id']}/telegram")
        assert retry.status_code == 200
        assert retry.json() == {"delivered": True, "telegram_status": "delivered"}
        assert client.post(f"/api/alerts/{alert['id']}/telegram").status_code == 409
        assert notifier.calls == 2
