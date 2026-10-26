from fastapi.testclient import TestClient

from schoolguard.db import now
from schoolguard.model_catalog import MODELS, requires_pro
from schoolguard.schemas import JobRequest


def test_catalog_advertises_actual_checkpoints_and_never_invents_fire_model(client):
    status = client.get("/api/system").json()
    indexed = {item["id"]: item for item in status["model_catalog"]}
    assert set(indexed) == set(MODELS)
    for name in ("yolov8n", "yolov8n-pose", "yolov9t", "yolov10n"):
        assert indexed[name]["tier"] == "free"
        assert indexed[name]["available"] is True
    for name in ("yolo11s", "yolo12n"):
        assert indexed[name]["tier"] == "pro_local"
        assert indexed[name]["available"] is True
    assert indexed["yolo26n"]["tier"] == "pro_local"
    assert indexed["yolo26n"]["available"] is False
    assert indexed["yolo12n"]["task"] == "detect"
    assert indexed["yolo12n"]["maturity"] == "research"
    assert "yolo13" not in indexed
    assert "yolo26-fire" not in indexed
    assert not requires_pro("yolov10n") and requires_pro("yolo11n")
    assert JobRequest(source_id="video", model="yolov8n-pose", detect_falls=True).detect_falls


def test_free_and_pro_model_gate_enforced_by_job_api(app):
    buyer = TestClient(app)
    registered = buyer.post("/api/register", json={
        "username": "model_buyer", "password": "a-unique-password-123",
        "display_name": "Khách model", "email": "model@example.test", "consent": True,
    })
    assert registered.status_code == 201
    uid = buyer.get("/api/me").json()["id"]
    app.state.telegram_linker.token = "test-token"
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
        (uid, "model-chat", now()),
    )
    path = app.state.settings.data_root / "training/videos/01_001.avi"
    source = buyer.post("/api/sources/upload", files={
        "file": ("model-test.avi", path.read_bytes(), "video/avi")
    }).json()["id"]
    for model in ("yolo11s", "yolo12n", "yolo26n"):
        assert buyer.post("/api/jobs", json={"source_id": source, "model": model}).status_code == 403
    for model in ("yolov8n-pose", "yolov9t", "yolov10n"):
        payload = {"source_id": source, "model": model}
        if model.endswith("-pose"):
            payload["detect_falls"] = True
        response = buyer.post("/api/jobs", json=payload)
        assert response.status_code == 202, response.text
    app.state.db.execute(
        "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
        "VALUES(?,'pro_local',NULL,'test',?) "
        "ON CONFLICT(user_id) DO UPDATE SET plan='pro_local',expires_at=NULL",
        (uid, now()),
    )
    (app.state.settings.models / "yolo26n.pt").write_bytes(b"test stub")
    for model in ("yolo11s", "yolo12n", "yolo26n"):
        response = buyer.post("/api/jobs", json={"source_id": source, "model": model})
        assert response.status_code == 202, response.text
