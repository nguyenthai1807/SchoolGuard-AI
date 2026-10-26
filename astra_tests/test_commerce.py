from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from schoolguard.app import create_app
from schoolguard.commerce import PayOSGateway, SmtpEmailSender, payos_signature, valid_public_url
from schoolguard.db import now


class FakeEmail:
    available = True

    def __init__(self):
        self.sent = []

    def send_verification(self, recipient, url):
        self.sent.append((recipient, url))

    def send_payment_confirmation(self, recipient, message):
        self.sent.append((recipient, message))


class FakePayOS:
    available = True
    key = "test-checksum-key"

    def create_checkout(self, code, amount, base_url, *, local_pilot=False):
        self.code = code
        self.amount = amount
        self.base_url = base_url
        self.local_pilot = local_pilot
        self.calls = getattr(self, "calls", 0) + 1
        return {"checkout_url": "https://pay.payos.vn/web/test-link",
                "payment_link_id": "test-link"}

    def verify_webhook(self, payload):
        return payload.get("signature") == payos_signature(payload.get("data", {}), self.key)


def make_webhook(gateway, **changes):
    data = {"orderCode": gateway.code, "amount": gateway.amount,
            "currency": "VND", "paymentLinkId": "test-link", "reference": "BANK-12345", "code": "00"}
    data.update(changes)
    return {"code": "00", "success": True, "data": data,
            "signature": payos_signature(data, gateway.key)}


def test_email_verification_and_signed_payment_webhook(app, tmp_path):
    mail, gateway = FakeEmail(), FakePayOS()
    settings = replace(app.state.settings, runtime=tmp_path / "commerce-runtime",
                       email_verification_required=True, payment_enabled=True,
                       public_base_url="https://lh25.vn")
    commerce = create_app(settings, email_sender=mail, payment_gateway=gateway)
    with TestClient(commerce) as customer:
        registered = customer.post("/api/register", json={
            "username": "paid_user", "password": "unique-long-password-123",
            "display_name": "Khách thử", "email": "paid@example.test", "consent": True,
        })
        assert registered.status_code == 201, registered.text
        assert registered.json()["email_sent"] is True
        assert customer.get("/api/me/commerce").json()["email_verified"] is False
        assert customer.post("/api/email/resend").status_code == 429
        assert customer.post("/api/orders/pro-local/checkout").status_code == 409
        assert customer.post("/api/orders/pro-local").status_code == 409
        token = mail.sent[0][1].split("#token=", 1)[1]
        assert customer.post("/api/email/verify", json={"token": token}).json() == {"verified": True}
        assert customer.post("/api/email/verify", json={"token": token}).status_code == 400
        assert customer.get("/api/me/commerce").json()["email_verified"] is True
        assert customer.post("/api/orders/pro-local/checkout").status_code == 409
        user_id = customer.get("/api/me").json()["id"]
        commerce.state.telegram_linker.token = "test-token"
        commerce.state.db.execute(
            "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
            (user_id, "123456789", now()),
        )
        checkout = customer.post("/api/orders/pro-local/checkout")
        assert checkout.status_code == 201, checkout.text
        assert checkout.json()["checkout_url"] == "https://pay.payos.vn/web/test-link"
        assert customer.post("/api/orders/pro-local/checkout").json()["id"] == checkout.json()["id"]
        assert customer.get("/api/me/plan").json()["plan"] == "free"
        with TestClient(commerce) as administrator:
            password = (settings.runtime / "admin-password.txt").read_text()
            assert administrator.post("/api/login", json={
                "username": "admin", "password": password,
            }).status_code == 200
            assert administrator.post("/api/admin/orders/any/activate", json={
                "payment_reference": "BANK-12345",
            }).status_code == 403
            created = administrator.post("/api/users", json={
                "username": "fresh_operator", "password": "another-long-password-123",
                "role": "operator",
            })
            assert created.status_code == 201
            users = administrator.get("/api/users").json()
            assert next(u for u in users if u["username"] == "fresh_operator")["plan"] == "free"
        body = make_webhook(gateway)
        tampered = {**body, "signature": "bad"}
        assert customer.post("/api/payments/payos/webhook", json=tampered).status_code == 400
        assert customer.post("/api/payments/payos/webhook", json=make_webhook(gateway, amount=1)).status_code == 409
        assert customer.get("/api/me/plan").json()["plan"] == "free"
        accepted = customer.post("/api/payments/payos/webhook", json=body)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["activated"] is True
        expiry = customer.get("/api/me/plan").json()["expires_at"]
        assert customer.get("/api/me/plan").json()["plan"] == "pro_local"
        assert customer.post("/api/payments/payos/webhook", json=body).json()["activated"] is False
        assert customer.get("/api/me/plan").json()["expires_at"] == expiry
        assert commerce.state.db.one("SELECT count(*) n FROM billing_notifications")["n"] == 2
        assert customer.get("/api/me/orders").json()[0]["status"] == "activated"
        assert customer.get("/api/admin/billing-notifications").status_code == 403
        assert customer.get("/api/admin/release-readiness").status_code == 403
        changed = customer.put("/api/profile", json={
            "display_name": "Khách thử", "email": "new-paid@example.test", "phone": "",
        })
        assert changed.status_code == 200
        assert customer.get("/api/me/commerce").json()["email_verified"] is False
        assert customer.post("/api/email/resend").status_code == 200
        assert mail.sent[-1][0] == "new-paid@example.test"


def test_commerce_fail_closed_without_real_configuration(app, tmp_path):
    assert not valid_public_url("https://demo.trycloudflare.com")
    assert not valid_public_url("http://lh25.vn")
    with TestClient(app) as client:
        assert client.get("/api/commerce/status").json()["payment_enabled"] is False
        registered = client.post("/api/register", json={
            "username": "free_user", "password": "unique-long-password-123",
            "display_name": "Khách thử", "email": "free@example.test", "consent": True,
        })
        assert registered.status_code == 201
        assert client.post("/api/orders/pro-local/checkout").status_code == 503
        assert client.post("/api/payments/payos/webhook", json={}).status_code == 503
    settings = replace(app.state.settings, runtime=tmp_path / "blocked-runtime",
                       email_verification_required=True, payment_enabled=True,
                       public_base_url="https://demo.trycloudflare.com")
    try:
        create_app(settings, email_sender=FakeEmail(), payment_gateway=FakePayOS())
    except RuntimeError as exc:
        assert "HTTPS" in str(exc)
    else:
        raise AssertionError("Temporary tunnel must not enable paid checkout")


def test_local_pilot_shows_payos_link_immediately_but_admin_approves_and_emails(app, tmp_path):
    mail, gateway = FakeEmail(), FakePayOS()
    settings = replace(app.state.settings, runtime=tmp_path / "pilot-runtime",
                       payment_enabled=False, public_base_url="")
    pilot = create_app(settings, email_sender=mail, payment_gateway=gateway)
    with TestClient(pilot, base_url="http://localhost:8770") as buyer:
        assert buyer.get("/api/commerce/status").json()["pilot_checkout_enabled"] is True
        registered = buyer.post("/api/register", json={
            "username": "pilot_buyer", "password": "unique-long-password-123",
            "display_name": "Khách thử", "email": "pilot@example.test", "consent": True,
        })
        assert registered.status_code == 201
        assert buyer.post("/api/orders/pro-local").status_code == 409
        uid = buyer.get("/api/me").json()["id"]
        pilot.state.db.execute(
            "INSERT INTO email_verifications(user_id,email,verified_at) VALUES(?,?,?)",
            (uid, "pilot@example.test", now()),
        )
        order = buyer.post("/api/orders/pro-local")
        assert order.status_code == 201, order.text
        body = order.json()
        assert body["checkout_url"] == "https://pay.payos.vn/web/test-link"
        assert body["amount_vnd"] == 29000
        assert gateway.local_pilot is True
        assert gateway.base_url == "http://localhost:8770"
        assert buyer.post("/api/orders/pro-local").json()["id"] == body["id"]
        assert gateway.calls == 1
        assert buyer.get("/api/me/plan").json()["pending_order"]["checkout_url"] == body["checkout_url"]
        assert buyer.get("/api/me/plan").json()["plan"] == "free"
        assert buyer.post(f"/api/me/orders/{body['id']}/report-transfer").status_code == 200
        assert buyer.get("/api/me/plan").json()["plan"] == "free"
        with TestClient(pilot, base_url="http://localhost:8770") as owner:
            password = (settings.runtime / "admin-password.txt").read_text()
            assert owner.post("/api/login", json={"username": "admin", "password": password}).status_code == 200
            admin_order = owner.get("/api/admin/orders").json()[0]
            assert admin_order["payment_order_code"] == gateway.code
            assert admin_order["status"] == "transfer_reported"
            assert owner.post(f"/api/admin/orders/{body['id']}/activate", json={
                "payment_reference": "PAYOS-PAID-001",
            }).status_code == 200
            assert owner.get("/api/admin/billing-notifications").json()[0]["status"] == "pending"
        assert buyer.get("/api/me/plan").json()["plan"] == "pro_local"
        assert pilot.state.billing_notifications.run_once() is True
        assert len(mail.sent) == 1
        assert mail.sent[0][0] == "pilot@example.test"
        assert "HƯỚNG DẪN BẮT ĐẦU VỚI LH25 PRO" in mail.sent[0][1]

    with TestClient(pilot, base_url="https://pilot.trycloudflare.com") as remote:
        assert remote.get("/api/commerce/status").json()["pilot_checkout_enabled"] is False


def test_local_pilot_ambiguous_gateway_failure_does_not_create_second_link(app, tmp_path):
    class UncertainPayOS(FakePayOS):
        def create_checkout(self, code, amount, base_url, *, local_pilot=False):
            super().create_checkout(code, amount, base_url, local_pilot=local_pilot)
            raise TimeoutError("Gateway timed out after receiving the order")

    gateway = UncertainPayOS()
    settings = replace(app.state.settings, runtime=tmp_path / "pilot-uncertain-runtime",
                       payment_enabled=False, public_base_url="")
    pilot = create_app(settings, email_sender=FakeEmail(), payment_gateway=gateway)
    with TestClient(pilot, base_url="http://localhost:8770") as buyer:
        registered = buyer.post("/api/register", json={
            "username": "uncertain_buyer", "password": "unique-long-password-123",
            "display_name": "Khách thử", "email": "uncertain@example.test", "consent": True,
        })
        assert registered.status_code == 201
        uid = buyer.get("/api/me").json()["id"]
        pilot.state.db.execute(
            "INSERT INTO email_verifications(user_id,email,verified_at) VALUES(?,?,?)",
            (uid, "uncertain@example.test", now()),
        )
        first = buyer.post("/api/orders/pro-local")
        assert first.status_code == 502
        pending = buyer.get("/api/me/plan").json()["pending_order"]
        assert pending["status"] == "requested"
        assert pending["payment_order_code"] == gateway.code
        assert pending["checkout_url"] is None
        assert buyer.post("/api/orders/pro-local").status_code == 409
        assert gateway.calls == 1
        assert buyer.get("/api/me/plan").json()["plan"] == "free"


def test_old_price_order_is_not_rewritten_or_reopened_at_new_price(app, tmp_path):
    gateway = FakePayOS()
    settings = replace(app.state.settings, runtime=tmp_path / "pilot-old-price-runtime",
                       payment_enabled=False, public_base_url="")
    pilot = create_app(settings, email_sender=FakeEmail(), payment_gateway=gateway)
    with TestClient(pilot, base_url="http://localhost:8770") as buyer:
        registered = buyer.post("/api/register", json={
            "username": "old_price_buyer", "password": "unique-long-password-123",
            "display_name": "Khách thử", "email": "old@example.test", "consent": True,
        })
        assert registered.status_code == 201
        uid = buyer.get("/api/me").json()["id"]
        pilot.state.db.execute(
            "INSERT INTO email_verifications(user_id,email,verified_at) VALUES(?,?,?)",
            (uid, "old@example.test", now()),
        )
        pilot.state.db.execute(
            "INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at,checkout_url) "
            "VALUES(?,?,'pro_local',149000,'requested',?,?)",
            ("old-price-order", uid, now(), "https://pay.payos.vn/web/old-order"),
        )
        pending = buyer.get("/api/me/plan").json()["pending_order"]
        assert pending["amount_vnd"] == 149000
        response = buyer.post("/api/orders/pro-local")
        assert response.status_code == 409
        assert "giá cũ" in response.json()["detail"]
        assert pilot.state.db.one("SELECT amount_vnd FROM orders WHERE id='old-price-order'")["amount_vnd"] == 149000
        assert getattr(gateway, "calls", 0) == 0


def test_signed_data_canonicalization():
    assert payos_signature({"orderCode": 123, "amount": 1000}, "key") == payos_signature(
        {"amount": 1000, "orderCode": 123}, "key")


def test_smtp_login_check_does_not_send_mail(monkeypatch):
    for key, value in {"SMTP_HOST": "smtp.gmail.com", "SMTP_PORT": "465",
                       "SMTP_USER": "owner@gmail.com", "SMTP_PASSWORD": "fake-app-password",
                       "SMTP_FROM": "owner@gmail.com"}.items():
        monkeypatch.setenv(key, value)
    calls = []

    class Connection:
        def __init__(self, host, port, **kwargs):
            assert host == "smtp.gmail.com" and port == 465
            assert kwargs.get("context") is not None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def login(self, username, password):
            calls.append("login")

        def send_message(self, message):
            calls.append("message")

    monkeypatch.setattr("schoolguard.commerce.smtplib.SMTP_SSL", Connection)
    assert SmtpEmailSender().check_connection()
    assert calls == ["login"]


def test_payos_link_adapter_uses_server_amount_and_validates_response(monkeypatch):
    monkeypatch.setenv("LH25_PAYOS_CLIENT_ID", "test-client")
    monkeypatch.setenv("LH25_PAYOS_API_KEY", "test-api-key")
    monkeypatch.setenv("LH25_PAYOS_CHECKSUM_KEY", "test-checksum")
    gateway = PayOSGateway()
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            data = {"orderCode": 123456789, "amount": 149000,
                    "checkoutUrl": "https://pay.payos.vn/web/abc", "paymentLinkId": "abc"}
            return {"code": "00", "data": data,
                    "signature": payos_signature(data, "test-checksum")}

    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("schoolguard.commerce.requests.post", fake_post)
    link = gateway.create_checkout(123456789, 149000, "https://lh25.vn")
    assert link["payment_link_id"] == "abc"
    sent = calls[0][1]["json"]
    assert sent["amount"] == 149000
    assert sent["returnUrl"] == "https://lh25.vn/payment-return"
    assert sent["signature"] == payos_signature({k: sent[k] for k in
        ("amount", "cancelUrl", "description", "orderCode", "returnUrl")}, "test-checksum")
    with pytest.raises(RuntimeError):
        gateway.create_checkout(123456789, 149000, "https://demo.trycloudflare.com")
    with pytest.raises(RuntimeError):
        gateway.create_checkout(123456789, 149000, "http://localhost:8770")
    gateway.create_checkout(123456789, 149000, "http://localhost:8770", local_pilot=True)
    assert calls[-1][1]["json"]["returnUrl"] == "http://localhost:8770/payment-return"


def test_signed_webhook_can_be_verified_before_checkout_is_enabled(app, tmp_path):
    gateway = FakePayOS()
    gateway.code, gateway.amount = 123, 149000
    settings = replace(app.state.settings, runtime=tmp_path / "webhook-setup", payment_enabled=False)
    setup_app = create_app(settings, payment_gateway=gateway)
    with TestClient(setup_app) as client:
        response = client.post("/api/payments/payos/webhook", json=make_webhook(gateway))
        assert response.status_code == 200
        assert response.json() == {"ok": True, "activated": False, "verification_only": True}
        assert setup_app.state.db.one("SELECT count(*) n FROM subscriptions")["n"] == 0
        assert setup_app.state.db.one("SELECT count(*) n FROM orders")["n"] == 0
        assert client.post("/api/payments/payos/webhook", json={}).status_code == 503
        admin_id = setup_app.state.db.one("SELECT id FROM users WHERE username='admin'")["id"]
        setup_app.state.db.execute(
            "INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at,payment_order_code) "
            "VALUES(?,?,'pro_local',?,'payment_pending',?,?)",
            ("pending-real-payment", admin_id, gateway.amount, now(), gateway.code),
        )
        assert client.post("/api/payments/payos/webhook", json=make_webhook(gateway)).status_code == 503
        assert setup_app.state.db.one("SELECT status FROM orders")["status"] == "payment_pending"


def test_webhook_registration_uses_only_configured_https_callback(monkeypatch):
    monkeypatch.setenv("LH25_PAYOS_CLIENT_ID", "test-client")
    monkeypatch.setenv("LH25_PAYOS_API_KEY", "test-api")
    monkeypatch.setenv("LH25_PAYOS_CHECKSUM_KEY", "test-checksum")
    gateway = PayOSGateway()
    calls = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"code": "00", "data": {"webhookUrl": "https://lh25.vn/api/payments/payos/webhook"}}

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return Response()

    monkeypatch.setattr("schoolguard.commerce.requests.post", post)
    assert gateway.register_webhook("https://lh25.vn") == "https://lh25.vn/api/payments/payos/webhook"
    assert calls[0][0] == "https://api-merchant.payos.vn/confirm-webhook"
    assert calls[0][1]["json"] == {"webhookUrl": "https://lh25.vn/api/payments/payos/webhook"}
    with pytest.raises(RuntimeError):
        gateway.register_webhook("https://temporary.trycloudflare.com")
    assert len(calls) == 1
