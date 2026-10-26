import sqlite3

from fastapi.testclient import TestClient

from astra_tests.conftest import FakeDetector
from schoolguard.db import Database, now
from schoolguard.telegram import TelegramNotifier
from schoolguard.telegram_link import TelegramLinker, recipient_for
from schoolguard.worker import Worker


def test_existing_telegram_binding_is_preserved_by_schema_upgrade(tmp_path):
    path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TABLE users(id INTEGER PRIMARY KEY, username TEXT, password TEXT, role TEXT)")
        conn.execute("INSERT INTO users VALUES(1,'admin','hash','admin')")
        conn.execute("CREATE TABLE telegram_accounts(user_id INTEGER PRIMARY KEY, chat_id TEXT, "
                     "verified_at TEXT)")
        conn.execute("INSERT INTO telegram_accounts VALUES(1,'123456','2026-10-20')")
    db = Database(path)
    row = db.one("SELECT chat_id,telegram_username FROM telegram_accounts WHERE user_id=1")
    assert row == {"chat_id": "123456", "telegram_username": ""}


def test_private_sources_jobs_alerts_and_faces(client, app):
    app.state.telegram_linker.token = "test-token"
    for name in ("customer_a", "customer_b"):
        assert client.post("/api/users", json={"username": name,
                           "password": "customer-test-password", "role": "operator"}).status_code == 201
    video = (app.state.settings.data_root / "training/videos/01_001.avi").read_bytes()
    owned = {}
    for name in ("customer_a", "customer_b"):
        user_id = app.state.db.one("SELECT id FROM users WHERE username=?", (name,))["id"]
        app.state.db.execute("INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
                             (user_id, str(user_id), now()))
        customer = TestClient(app)
        assert customer.post("/api/login", json={"username": name,
                             "password": "customer-test-password"}).status_code == 200
        assert customer.put("/api/profile", json={"display_name": name,
                            "email": f"{name}@example.test"}).status_code == 200
        source = customer.post("/api/sources/upload", files={"file": ("home.avi", video,
                               "video/avi")}).json()["id"]
        job = customer.post("/api/jobs", json={"source_id": source, "model": "yolo11s"})
        assert job.status_code == 202, job.text
        owned[name] = (customer, source, job.json()["id"])
    a, source_a, job_a = owned["customer_a"]
    b, source_b, job_b = owned["customer_b"]
    assert [s["id"] for s in a.get("/api/sources").json()["items"]] == [source_a]
    assert [s["id"] for s in b.get("/api/sources").json()["items"]] == [source_b]
    assert a.get(f"/api/sources/{source_b}").status_code == 404
    assert a.get(f"/api/sources/{source_b}/thumbnail").status_code == 404
    assert a.post("/api/jobs", json={"source_id": source_b, "model": "yolo11s"}).status_code == 404
    assert [j["id"] for j in a.get("/api/jobs").json()["items"]] == [job_a]
    assert a.get(f"/api/jobs/{job_b}").status_code == 404
    assert a.post(f"/api/jobs/{job_b}/cancel").status_code == 404

    alert_id = "alert_of_b"
    app.state.db.execute(
        "INSERT INTO alerts(id,job_id,created_at,video_time,zone,track_id,confidence,"
        "bbox,dwell,evidence,event_type,severity,details) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (alert_id, job_b, now(), 2, "Té ngã", 1, .9, "[0,0,1,1]", 1, "proof.jpg",
         "suspected_fall", "urgent", "{}"),
    )
    folder = app.state.settings.runtime / "jobs" / job_b
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "proof.jpg").write_bytes(b"proof")
    (folder / "people.json").write_text('{"items":[{"track_id":1,"image":"person-1.jpg"}],"count":1}')
    (folder / "person-1.jpg").write_bytes(b"private image")
    faces = app.state.settings.runtime / "faces"
    faces.mkdir(exist_ok=True)
    (faces / "face_of_b.jpg").write_bytes(b"face")
    app.state.db.execute(
        "INSERT INTO faces(id,scope,kind,job_id,day,ordinal,first_seen,last_seen,"
        "video_time,seen_count,confidence,embedding,image) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        ("face_of_b", job_b, "video", job_b, "2026-10-20", 1, now(), now(), 1, 2, .9,
         b"embedding", "face_of_b.jpg"),
    )
    assert a.get("/api/alerts").json()["total"] == 0
    assert a.get(f"/api/alerts?job_id={job_b}").status_code == 404
    assert a.get(f"/api/alerts/{alert_id}/evidence").status_code == 404
    assert a.patch(f"/api/alerts/{alert_id}", json={"status": "resolved"}).status_code == 404
    assert alert_id not in a.get("/api/export/alerts.csv").text
    assert a.get(f"/api/faces?job_id={job_b}").status_code == 404
    assert a.get("/api/faces/face_of_b/image").status_code == 404
    assert a.get(f"/api/jobs/{job_b}/people").status_code == 404
    assert a.get(f"/api/jobs/{job_b}/people/1/image").status_code == 404
    assert b.get("/api/alerts").json()["total"] == 1
    assert b.get("/api/faces/face_of_b/image").status_code == 200
    assert b.get(f"/api/jobs/{job_b}/people").json()["count"] == 1
    assert b.get(f"/api/jobs/{job_b}/people/1/image").status_code == 200
    assert client.get("/api/alerts").json()["total"] == 1


def test_unlinked_customer_cannot_start_analysis(client, app):
    client.post("/api/users", json={"username": "new_customer", "password": "test-password-123",
                                    "role": "operator"})
    customer = TestClient(app)
    customer.post("/api/login", json={"username": "new_customer", "password": "test-password-123"})
    assert customer.get("/api/telegram/status").json()["linked"] is False
    assert customer.post("/api/jobs", json={"source_id": "anything", "model": "yolo11s"}).status_code == 409
    assert customer.post("/api/live/start", json={"source_id": "live", "model": "yolo11s"}).status_code == 409
    assert customer.put("/api/profile", json={"display_name": "New customer",
                        "email": "invalid"}).status_code == 422
    assert customer.put("/api/profile", json={"display_name": "New customer",
                        "email": "new@example.test"}).status_code == 200
    assert customer.post("/api/jobs", json={"source_id": "anything", "model": "yolo11s"}).status_code == 409


def test_telegram_pairing_and_private_delivery(tmp_path):
    db = Database(tmp_path / "test.sqlite3")
    db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'admin','x','admin')")
    db.execute("INSERT INTO users(id,username,password,role) VALUES(2,'customer','x','operator')")

    class Result:
        def __init__(self, result):
            self.result = result

        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True, "result": self.result}

    class Session:
        command = None

        def get(self, url, **kwargs):
            if url.endswith("/getMe"):
                return Result({"username": "LH25_Test_Bot"})
            assert url.endswith("/getUpdates")
            return Result([{"update_id": 1, "message": {"text": self.command,
                           "chat": {"type": "private", "id": 234567},
                           "from": {"id": 234567, "username": "my_customer"}}}])

        def post(self, url, **kwargs):
            assert url.endswith("/sendMessage")
            assert kwargs["data"]["chat_id"] == "234567"
            return Result({"message_id": 1})

    session = Session()
    linker = TelegramLinker(db, "bot-token", session=session)
    started = linker.begin(2)
    assert started["url"].startswith("https://t.me/LH25_Test_Bot?start=")
    session.command = started["command"]
    assert linker.check(2)["linked"] is True
    assert linker.status(2)["telegram_username"] == "my_customer"
    assert linker.status(1)["linked"] is False
    assert db.one("SELECT chat_id FROM telegram_accounts WHERE user_id=2")["chat_id"] == "234567"
    shared = TelegramNotifier(token="bot-token", chat_id="admin-chat", session=session)
    assert recipient_for(db, 2, shared).chat_id == "234567"
    assert recipient_for(db, 1, shared).chat_id == "admin-chat"
    linker.disconnect(2)
    assert recipient_for(db, 2, shared).configured is False


def test_video_alert_goes_to_the_owner_chat_not_admin(client, app):
    app.state.telegram_linker.token = "test-token"
    client.post("/api/users", json={"username": "customer", "password": "test-password-123",
                                    "role": "operator"})
    owner = app.state.db.one("SELECT id FROM users WHERE username='customer'")["id"]
    app.state.db.execute("INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
                         (owner, "owner-chat", now()))
    customer = TestClient(app)
    customer.post("/api/login", json={"username": "customer", "password": "test-password-123"})
    customer.put("/api/profile", json={"display_name": "Customer",
                                       "email": "customer@example.test"})
    video = (app.state.settings.data_root / "training/videos/01_001.avi").read_bytes()
    source = customer.post("/api/sources/upload", files={"file": ("fall.avi", video,
                            "video/avi")}).json()["id"]
    payload = {"source_id": source, "model": "yolo11s", "dwell_seconds": 0.5,
               "zones": [{"name": "home", "points": [[0, 0], [1, 0], [1, 1], [0, 1]]}]}
    job_id = customer.post("/api/jobs", json=payload).json()["id"]

    class Result:
        def raise_for_status(self):
            pass

        def json(self):
            return {"ok": True}

    class Session:
        def __init__(self):
            self.destinations = []

        def post(self, url, **kwargs):
            assert url.endswith("/sendPhoto")
            self.destinations.append(kwargs["data"]["chat_id"])
            return Result()

    session = Session()
    notifier = TelegramNotifier(token="test-token", chat_id="legacy-admin", session=session)
    Worker(app.state.db, app.state.settings, detector_factory=FakeDetector,
           notifier=notifier).run(app.state.db.one("SELECT * FROM jobs WHERE id=?", (job_id,)))
    assert customer.get(f"/api/jobs/{job_id}").json()["status"] == "completed"
    assert customer.get(f"/api/alerts?job_id={job_id}").json()["items"][0]["telegram_status"] == "delivered"
    assert session.destinations == ["owner-chat"]
    queued = customer.post("/api/jobs", json=payload).json()["id"]
    assert customer.delete("/api/telegram/link").status_code == 200
    assert customer.get(f"/api/jobs/{queued}").json()["status"] == "cancelled"
    assert customer.post("/api/jobs", json=payload).status_code == 409
