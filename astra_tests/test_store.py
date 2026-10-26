from fastapi.testclient import TestClient

from schoolguard.db import now
from schoolguard.plans import (PRO_VIDEO_LIMIT, PRO_UPLOAD_BYTES, PRO_VIDEO_SECONDS,
                               PRO_WEBCAM_SECONDS_PER_DAY, usage_day)
from schoolguard.schemas import JobRequest


def register(customer, username="new_home"):
    return customer.post("/api/register", json={
        "username": username,
        "password": "a-unique-password-123",
        "display_name": "Khách LH25",
        "email": f"{username}@example.test",
        "consent": True,
    })


def test_public_store_registration_and_isolated_free_account(client, app):
    assert client.get("/store").status_code == 200
    assert "Gói dịch vụ" in client.get("/store").text
    assert "29.000₫" in client.get("/store").text
    assert "149.000₫" not in client.get("/store").text
    assert 'id="product-shots"' in client.get("/store").text
    for image in ("demo-library.webp", "demo-plan.webp"):
        response = client.get(f"/static/{image}")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/webp")
        assert response.content
    assert "Thông tin quyền riêng tư" in client.get("/privacy").text
    assert "Điều khoản thử nghiệm" in client.get("/terms").text
    customer = TestClient(app)
    assert customer.post("/api/register", json={"username": "unauthorized", "role": "admin"}).status_code == 422
    result = register(customer)
    assert result.status_code == 201, result.text
    assert result.json()["role"] == "operator"
    assert customer.get("/api/me/plan").json()["plan"] == "free"
    assert customer.get("/api/me/plan").json()["pro_price_vnd"] == 29000
    assert customer.get("/api/users").status_code == 403
    assert customer.post("/api/jobs", json={"source_id": "missing", "model": "yolo11s"}).status_code == 409
    assert register(TestClient(app), "new_home").status_code == 409


def test_free_quota_and_manual_pro_activation(client, app):
    customer = TestClient(app)
    assert register(customer).status_code == 201
    user_id = customer.get("/api/me").json()["id"]
    app.state.telegram_linker.token = "test-token"
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
        (user_id, "123456789", now()),
    )
    path = app.state.settings.data_root / "training/videos/01_001.avi"
    uploaded = customer.post("/api/sources/upload", files={"file": ("home.avi", path.read_bytes(), "video/avi")})
    assert uploaded.status_code == 201, uploaded.text
    source_id = uploaded.json()["id"]
    assert customer.post("/api/live/start", json={"source_id": "camera", "model": "yolo11s"}).status_code == 403
    assert customer.post("/api/jobs", json={"source_id": source_id, "model": "yolo11s", "recognize_faces": True}).status_code == 403
    assert customer.post("/api/jobs", json={"source_id": source_id, "model": "yolo11s"}).status_code == 403
    for _ in range(3):
        assert customer.post("/api/jobs", json={"source_id": source_id, "model": "yolov8n"}).status_code == 202
    assert customer.get("/api/me/plan").json()["video_used"] == 3
    assert customer.post("/api/jobs", json={"source_id": source_id, "model": "yolov8n"}).status_code == 429

    order = customer.post("/api/orders/pro-local")
    assert order.status_code == 201, order.text
    order_id = order.json()["id"]
    assert customer.post("/api/orders/pro-local").status_code == 409
    assert customer.get("/api/admin/orders").status_code == 403
    assert client.post(f"/api/admin/orders/{order_id}/activate", json={"payment_reference": "BANK-TXN-001"}).status_code == 200
    assert client.post(f"/api/admin/orders/{order_id}/activate", json={"payment_reference": "BANK-TXN-001"}).status_code == 409
    assert customer.get("/api/me/plan").json()["plan"] == "pro_local"
    assert customer.get("/api/me/plan").json()["webcam"] is True
    assert customer.post("/api/jobs", json={"source_id": source_id, "model": "yolo11s"}).status_code == 202
    app.state.db.execute(
        "UPDATE subscriptions SET expires_at='2000-01-01T00:00:00+00:00' WHERE user_id=?",
        (user_id,),
    )
    assert customer.get("/api/me/plan").json()["plan"] == "free"
    assert customer.post("/api/live/start", json={"source_id": "camera", "model": "yolo11s"}).status_code == 403
    assert customer.post("/api/jobs", json={"source_id": source_id, "model": "yolov8n"}).status_code == 429


def test_free_rejects_video_over_two_minutes(client, app, monkeypatch):
    customer = TestClient(app)
    assert register(customer).status_code == 201
    user_id = customer.get("/api/me").json()["id"]
    app.state.telegram_linker.token = "test-token"
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
        (user_id, "123456789", now()),
    )
    path = app.state.settings.data_root / "training/videos/01_001.avi"
    uploaded = customer.post("/api/sources/upload", files={"file": ("home.avi", path.read_bytes(), "video/avi")})
    assert uploaded.status_code == 201
    monkeypatch.setattr("schoolguard.app.metadata", lambda row: {"duration": 121})
    denied = customer.post("/api/jobs", json={"source_id": uploaded.json()["id"], "model": "yolo11s"})
    assert denied.status_code == 403
    assert customer.get("/api/me/plan").json()["video_used"] == 0


def test_rejected_order_never_grants_pro(client, app):
    customer = TestClient(app)
    assert register(customer).status_code == 201
    order_id = customer.post("/api/orders/pro-local").json()["id"]
    assert client.post(f"/api/admin/orders/{order_id}/reject").status_code == 200
    assert customer.get("/api/me/plan").json()["plan"] == "free"
    assert client.post(f"/api/admin/orders/{order_id}/activate", json={"payment_reference": "BANK-TXN-002"}).status_code == 409


def test_manual_transfer_needs_owner_report_and_admin_bank_confirmation(client, app):
    customer = TestClient(app)
    stranger = TestClient(app)
    assert register(customer, "manual_buyer").status_code == 201
    assert register(stranger, "other_buyer").status_code == 201
    order = customer.post("/api/orders/pro-local")
    assert order.status_code == 201
    order_id = order.json()["id"]
    assert customer.get("/api/me/commerce").json()["manual_transfer"] is None
    assert customer.post(f"/api/me/orders/{order_id}/report-transfer").status_code == 409
    assert customer.get("/api/me/plan").json()["plan"] == "free"

    app.state.settings.manual_bank_name = "Test Bank"
    app.state.settings.manual_bank_account = "000000000"
    app.state.settings.manual_bank_recipient = "TEST RECIPIENT"
    details = customer.get("/api/me/commerce").json()["manual_transfer"]
    assert details == {"bank": "Test Bank", "account": "000000000", "recipient": "TEST RECIPIENT"}
    assert stranger.post(f"/api/me/orders/{order_id}/report-transfer").status_code == 404
    assert customer.post(f"/api/me/orders/{order_id}/report-transfer").json()["status"] == "transfer_reported"
    assert customer.post(f"/api/me/orders/{order_id}/report-transfer").status_code == 404
    assert customer.post("/api/orders/pro-local").status_code == 409
    assert customer.get("/api/me/plan").json()["pending_order"]["status"] == "transfer_reported"
    assert customer.get("/api/me/plan").json()["plan"] == "free"
    assert client.get("/api/admin/orders").json()[0]["status"] == "transfer_reported"
    activated = client.post(f"/api/admin/orders/{order_id}/activate", json={
        "payment_reference": "REAL-STATEMENT-123",
    })
    assert activated.status_code == 200, activated.text
    assert customer.get("/api/me/plan").json()["plan"] == "pro_local"
    assert app.state.db.one("SELECT paid_at FROM orders WHERE id=?", (order_id,))["paid_at"]
    assert app.state.db.one("SELECT count(*) n FROM billing_notifications WHERE order_id=?",
                            (order_id,))["n"] == 2


def test_manual_payos_link_is_order_scoped_and_never_auto_activates(client, app):
    buyer = TestClient(app)
    other = TestClient(app)
    assert register(buyer, "payos_buyer").status_code == 201
    assert register(other, "payos_other").status_code == 201
    order_id = buyer.post("/api/orders/pro-local").json()["id"]
    other_order_id = other.post("/api/orders/pro-local").json()["id"]
    endpoint = f"/api/admin/orders/{order_id}/manual-payos-link"
    link = "https://pay.payos.vn/web/abc123456789"
    assert buyer.post(f"/api/me/orders/{order_id}/report-transfer").status_code == 409
    assert buyer.post(endpoint, json={"url": link}).status_code == 403
    for unsafe in ("http://pay.payos.vn/web/abc123456789",
                   "https://pay.payos.vn.evil.test/web/abc123456789",
                   "https://pay.payos.vn@evil.test/web/abc123456789",
                   "https://pay.payos.vn/web/abc123456789?redirect=evil"):
        assert client.post(endpoint, json={"url": unsafe}).status_code == 422
    assert client.post(endpoint, json={"url": link}).status_code == 200
    assert client.post(endpoint, json={"url": link}).status_code == 409
    assert client.post(f"/api/admin/orders/{other_order_id}/manual-payos-link",
                       json={"url": link}).status_code == 409
    assert buyer.get("/api/me/plan").json()["pending_order"]["checkout_url"] == link
    assert other.get("/api/me/orders").json()[0]["checkout_url"] is None
    assert buyer.get("/api/me/plan").json()["plan"] == "free"
    assert buyer.post(f"/api/me/orders/{order_id}/report-transfer").status_code == 200
    assert buyer.get("/api/me/plan").json()["plan"] == "free"
    assert client.post(f"/api/admin/orders/{order_id}/activate", json={
        "payment_reference": "PAYOS-TXN-100",
    }).status_code == 200
    assert buyer.get("/api/me/plan").json()["plan"] == "pro_local"


def test_pro_quota_is_enforced_on_server(client, app):
    customer = TestClient(app)
    assert register(customer, "pro_limit").status_code == 201
    uid = customer.get("/api/me").json()["id"]
    app.state.telegram_linker.token = "test-token"
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
        (uid, "customer-chat", now()),
    )
    app.state.db.execute(
        "UPDATE subscriptions SET plan='pro_local',expires_at=NULL,source='test',updated_at=? "
        "WHERE user_id=?", (now(), uid),
    )
    plan = customer.get("/api/me/plan").json()
    assert plan["video_limit"] == PRO_VIDEO_LIMIT
    assert plan["video_seconds"] == PRO_VIDEO_SECONDS
    assert plan["upload_bytes"] == PRO_UPLOAD_BYTES
    assert plan["webcam_seconds_per_day"] == PRO_WEBCAM_SECONDS_PER_DAY
    path = app.state.settings.data_root / "training/videos/01_001.avi"
    source = customer.post("/api/sources/upload", files={
        "file": ("home.avi", path.read_bytes(), "video/avi")
    }).json()["id"]
    with app.state.db.connect() as conn:
        for number in range(PRO_VIDEO_LIMIT):
            conn.execute(
                "INSERT INTO jobs(id,source_id,status,created_at,config,user_id,quota_charged) "
                "VALUES(?,?,'completed',?,?,?,1)",
                (f"pro-quota-{number}", source, now(), "{}", uid),
            )
    assert customer.get("/api/me/plan").json()["video_used"] == PRO_VIDEO_LIMIT
    denied = customer.post("/api/jobs", json={"source_id": source, "model": "yolo11s"})
    assert denied.status_code == 429, denied.text


def test_pro_webcam_daily_limit_is_enforced_before_model_load(client, app):
    customer = TestClient(app)
    assert register(customer, "camera_limit").status_code == 201
    uid = customer.get("/api/me").json()["id"]
    app.state.telegram_linker.token = "test-token"
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
        (uid, "customer-chat", now()),
    )
    app.state.db.execute("UPDATE subscriptions SET plan='pro_local' WHERE user_id=?", (uid,))
    app.state.db.execute(
        "INSERT INTO daily_camera_usage(user_id,day,seconds) VALUES(?,?,?)",
        (uid, usage_day(), PRO_WEBCAM_SECONDS_PER_DAY),
    )
    plan = customer.get("/api/me/plan").json()
    assert plan["webcam_used_seconds_today"] == PRO_WEBCAM_SECONDS_PER_DAY
    response = customer.post("/api/live/start", json={"source_id": "live", "model": "yolo11s"})
    assert response.status_code == 429, response.text


def test_effort_changes_actual_inference_settings_and_free_gate(client, app):
    low = JobRequest(source_id="video", effort="low")
    extra = JobRequest(source_id="video", effort="extra_max")
    assert (low.image_size, low.stride) == (640, 5)
    assert (extra.image_size, extra.stride) == (960, 1)
    customer = TestClient(app)
    assert register(customer, "effort_user").status_code == 201
    uid = customer.get("/api/me").json()["id"]
    app.state.telegram_linker.token = "test-token"
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
        (uid, "customer-chat", now()),
    )
    path = app.state.settings.data_root / "training/videos/01_001.avi"
    source = customer.post("/api/sources/upload", files={
        "file": ("home.avi", path.read_bytes(), "video/avi")
    }).json()["id"]
    response = customer.post("/api/jobs", json={
        "source_id": source, "model": "yolo11s", "effort": "extra_max"})
    assert response.status_code == 403
    assert customer.post("/api/jobs", json={
        "source_id": source, "model": "yolov8n", "effort": "low"}).status_code == 202
