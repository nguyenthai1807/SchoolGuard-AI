from schoolguard.billing_notifications import BillingNotifications, enqueue_receipts
from schoolguard.db import now
from schoolguard.telegram import TelegramNotifier


def test_receipts_are_durable_retryable_and_keep_recipient_ownership(client, app):
    db = app.state.db
    user_id = client.get("/api/me").json()["id"]
    db.execute("INSERT INTO customer_profiles VALUES(?,?,?,?,?)",
               (user_id, "Receipt test", "buyer@example.test", "", now()))
    db.execute("INSERT INTO email_verifications(user_id,email,verified_at) VALUES(?,?,?)",
               (user_id, "buyer@example.test", now()))
    db.execute("INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(?,?,?)",
               (user_id, "buyer-chat", now()))
    db.execute("INSERT INTO subscriptions VALUES(?,?,?,?,?)",
               (user_id, "pro_local", "2030-01-01T00:00:00+00:00", "payos_webhook", now()))
    db.execute("INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at) VALUES(?,?,?,?,?,?)",
               ("receipt-order", user_id, "pro_local", 149000, "activated", now()))
    with db.connect() as conn:
        enqueue_receipts(conn, "receipt-order")
        enqueue_receipts(conn, "receipt-order")
    assert db.one("SELECT count(*) n FROM billing_notifications")["n"] == 2

    class Mail:
        failed = False
        sent = []

        def send_payment_confirmation(self, recipient, message):
            assert recipient == "buyer@example.test"
            if not self.failed:
                self.failed = True
                raise RuntimeError("simulated SMTP outage")
            self.sent.append(message)

    class Session:
        calls = 0

        def post(self, url, **kwargs):
            assert kwargs["data"]["chat_id"] == "buyer-chat"
            self.calls += 1
            class Response:
                def raise_for_status(self):
                    pass

                def json(self):
                    return {"ok": True}
            return Response()

    mail, session = Mail(), Session()
    notifier = TelegramNotifier(token="fake-bot", chat_id="wrong-legacy-chat", session=session)
    worker = BillingNotifications(db, mail, notifier)
    assert worker.run_once()  # Email fails and remains pending, Pro stays active.
    assert db.one("SELECT status FROM billing_notifications WHERE channel='email'")["status"] == "pending"
    assert worker.run_once()  # Telegram succeeds using the buyer's chat.
    db.execute("UPDATE billing_notifications SET next_attempt=0 WHERE status='pending'")
    # A fresh dispatcher after restart can finish the durable pending receipt.
    assert BillingNotifications(db, mail, notifier).run_once()
    assert not worker.run_once()
    assert session.calls == 1 and len(mail.sent) == 1
    assert 'HƯỚNG DẪN BẮT ĐẦU' in mail.sent[0]
    assert 'Telegram' in mail.sent[0] and 'Webcam' in mail.sent[0]
    assert all(row["status"] == "delivered" for row in db.all("SELECT status FROM billing_notifications"))
    assert client.get("/api/me/plan").json()["plan"] == "admin"


def test_readiness_never_claims_sqlite_is_cloud_ready(client):
    response = client.get("/api/admin/release-readiness")
    assert response.status_code == 200
    report = response.json()
    assert report["production_ready"] is False
    assert not next(row for row in report["checks"] if row["id"] == "cloud_database")["ok"]
    assert {"local_database", "worker", "model", "google", "google_admin", "telegram", "payos_local", "smtp_local"} <= {
        row["id"] for row in report["local_checks"]
    }
    assert all(row["next_step"] for row in report["local_checks"] + report["checks"])
    assert all(isinstance(row["ok"], bool) for row in report["local_checks"])


def test_admin_cannot_send_guide_for_unpaid_order(client, app):
    db = app.state.db
    uid = client.get('/api/me').json()['id']
    db.execute("INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at) VALUES(?,?,?,?,?,?)",
               ('unpaid-guide', uid, 'pro_local', 149000, 'requested', now()))
    assert client.post('/api/admin/orders/unpaid-guide/resend-guide').status_code == 409
    assert client.post('/api/admin/orders/missing/resend-guide').status_code == 404
    assert not db.all('SELECT * FROM billing_notifications')


def test_resend_activated_guide_is_queued_once_without_reactivation(client, app):
    db = app.state.db
    uid = client.get('/api/me').json()['id']
    db.execute("INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at) VALUES(?,?,?,?,?,?)",
               ('paid-guide', uid, 'pro_local', 149000, 'activated', now()))
    assert client.post('/api/admin/orders/paid-guide/resend-guide').status_code == 202
    assert client.post('/api/admin/orders/paid-guide/resend-guide').status_code == 429
    assert db.one('SELECT count(*) n FROM billing_notifications')["n"] == 1
    assert db.one("SELECT status FROM orders WHERE id='paid-guide'")["status"] == 'activated'
