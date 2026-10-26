from schoolguard.auth import hash_password
from schoolguard.db import now


def test_bell_tracks_video_and_pro_per_account(client, app):
    db = app.state.db
    password = "test-user-password-123"
    for username in ("notify_alice", "notify_bob"):
        db.execute(
            "INSERT INTO users(username,password,role) VALUES(?,?,?)",
            (username, hash_password(password), "operator"),
        )
    alice = db.one("SELECT id FROM users WHERE username='notify_alice'")["id"]
    bob = db.one("SELECT id FROM users WHERE username='notify_bob'")["id"]
    for name in ("alice-video", "bob-video"):
        db.execute(
            "INSERT INTO sources(id,name,path,kind,split) VALUES(?,?,?,?,?)",
            (name, name + ".mp4", "test.mp4", "video", "uploaded"),
        )
    for ident, source, status, owner in (
        ("alice-done", "alice-video", "completed", alice),
        ("alice-error", "alice-video", "failed", alice),
        ("alice-running", "alice-video", "running", alice),
        ("bob-done", "bob-video", "completed", bob),
        ("alice-live", "alice-live", "completed", alice),
    ):
        if ident == "alice-live":
            db.execute(
                "INSERT INTO sources(id,name,path,kind,split) VALUES(?,?,?,?,?)",
                (ident, "Webcam", "test.mp4", "live", "uploaded"),
            )
        db.execute(
            "INSERT INTO jobs(id,source_id,status,created_at,finished_at,config,user_id) "
            "VALUES(?,?,?,?,?,?,?)",
            (ident, source, status, now(), now(), "{}", owner),
        )
    db.execute(
        "INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at,resolved_at) "
        "VALUES(?,?,?,?,?,?,?)",
        ("alice-pro", alice, "pro_local", 49_000, "activated", now(), now()),
    )
    assert 'id="notification-bell"' in client.get("/").text

    assert client.post("/api/login", json={"username": "notify_alice", "password": password}).status_code == 200
    response = client.get("/api/notifications")
    assert response.status_code == 200
    data = response.json()
    assert {item["id"] for item in data["items"]} == {
        "job:alice-done", "job:alice-error", "order:alice-pro",
    }
    assert data["unread"] == 3
    assert client.post("/api/notifications/job:alice-done/read").json() == {"read": True}
    assert client.get("/api/notifications").json()["unread"] == 2
    assert client.post("/api/notifications/read-all").json()["unread"] == 0
    assert client.get("/api/notifications").json()["unread"] == 0

    assert client.post("/api/login", json={"username": "notify_bob", "password": password}).status_code == 200
    data = client.get("/api/notifications").json()
    assert [item["id"] for item in data["items"]] == ["job:bob-done"]
    assert data["unread"] == 1
    assert client.post("/api/notifications/order:alice-pro/read").status_code == 404
    assert client.post("/api/notifications/job:alice-done/read").status_code == 404


def test_notifications_require_login(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        assert client.get("/api/notifications").status_code == 401
        assert client.post("/api/notifications/read-all").status_code == 401
