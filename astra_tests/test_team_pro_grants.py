from fastapi.testclient import TestClient
import pytest

import schoolguard.google_login as google_login
from schoolguard.team_grants import provision


def google_customer(app, monkeypatch, email="teammate@example.test", verified=True):
    app.state.settings.google_client_id = "test.apps.googleusercontent.com"
    customer = TestClient(app)
    nonce = customer.get("/api/auth/google/config").json()["nonce"]
    monkeypatch.setattr(google_login, "verify_identity", lambda token, audience: {
        "sub": "verified-team-subject", "email": email,
        "email_verified": verified, "name": "Teammate", "nonce": nonce,
    })
    return customer


def sign_in(customer):
    return customer.post(
        "/api/auth/google", headers={"Origin": "http://testserver"},
        json={"credential": "test-credential-long-enough", "consent": True},
    )


def test_pending_team_pro_redeems_only_after_verified_google_login(app, monkeypatch):
    db = app.state.db
    assert provision(db, "  TEAMMATE@example.test ") == "pending_google_login"
    assert provision(db, "teammate@example.test") == "pending_google_login"
    customer = google_customer(app, monkeypatch, verified=False)
    assert sign_in(customer).status_code == 401
    assert db.one("SELECT applied_user_id FROM team_pro_grants WHERE email=?",
                  ("teammate@example.test",))["applied_user_id"] is None
    customer = google_customer(app, monkeypatch)
    response = sign_in(customer)
    assert response.status_code == 200
    assert response.json()["role"] == "operator"
    assert customer.get("/api/me/plan").json()["plan"] == "pro_local"
    assert db.one("SELECT plan,expires_at,source FROM subscriptions WHERE user_id=?",
                  (response.json()["id"],)) == {
                      "plan": "pro_local", "expires_at": None, "source": "team_grant"}
    grant = db.one("SELECT applied_user_id FROM team_pro_grants WHERE email=?",
                   ("teammate@example.test",))
    assert grant["applied_user_id"] == response.json()["id"]
    assert db.one("SELECT count(*) n FROM orders")["n"] == 0
    assert provision(db, "teammate@example.test") == "already_granted"


def test_existing_verified_google_account_activates_without_order(app, monkeypatch):
    customer = google_customer(app, monkeypatch)
    response = sign_in(customer)
    assert response.status_code == 200
    assert customer.get("/api/me/plan").json()["plan"] == "free"
    assert provision(app.state.db, "teammate@example.test") == "activated"
    assert customer.get("/api/me/plan").json()["plan"] == "pro_local"
    assert app.state.db.one("SELECT count(*) n FROM orders")["n"] == 0


def test_changed_google_email_does_not_redeem_against_old_profile(app, monkeypatch):
    customer = google_customer(app, monkeypatch, email="old@example.test")
    assert sign_in(customer).status_code == 200
    assert provision(app.state.db, "new@example.test") == "pending_google_login"
    nonce = customer.get("/api/auth/google/config").json()["nonce"]
    monkeypatch.setattr(google_login, "verify_identity", lambda token, audience: {
        "sub": "verified-team-subject", "email": "new@example.test",
        "email_verified": True, "name": "Teammate", "nonce": nonce,
    })
    assert sign_in(customer).status_code == 200
    assert customer.get("/api/me/plan").json()["plan"] == "free"
    grant = app.state.db.one(
        "SELECT applied_user_id FROM team_pro_grants WHERE email=?",
        ("new@example.test",),
    )
    assert grant["applied_user_id"] is None


def test_admin_and_unlinked_local_accounts_are_not_granted_by_email_alone(app):
    db = app.state.db
    with TestClient(app):
        pass
    db.execute(
        "INSERT INTO customer_profiles(user_id,display_name,email,phone,updated_at) "
        "VALUES(1,'Admin','admin@example.test','',datetime('now'))"
    )
    assert provision(db, "admin@example.test") == "already_admin"
    with db.connect() as conn:
        uid = conn.execute(
            "INSERT INTO users(username,password,role) "
            "VALUES('local-team','unused','operator')"
        ).lastrowid
        conn.execute(
            "INSERT INTO customer_profiles"
            "(user_id,display_name,email,phone,updated_at) "
            "VALUES(?,'Local','local@example.test','',datetime('now'))", (uid,)
        )
    assert provision(db, "local@example.test") == "unlinked_account"
    assert db.one("SELECT count(*) n FROM team_pro_grants")["n"] == 0
    with pytest.raises(ValueError):
        provision(db, "not-an-email")
