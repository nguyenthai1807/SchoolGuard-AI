import sys
from types import ModuleType

import pytest

from schoolguard.cloud_auth import (
    CloudAuthRejected, CloudAuthUnavailable, FirebaseTokenVerifier,
    bearer_token, principal_from_claims,
)


TOKEN = ".".join(["a" * 10, "b" * 10, "c" * 10])
GOOGLE_CLAIMS = {
    "uid": "firebase-uid-1", "email": "owner@example.com",
    "email_verified": True, "firebase": {"sign_in_provider": "google.com"},
    "role": "admin",  # Client-side role claims must not become authority.
}


@pytest.mark.parametrize("header", [
    None, "", "Basic abc", "Bearer", "Bearer fake-token", "Bearer a.b.c extra",
    "Bearer " + "a" * 8200, "Bearer a.b.c\nOther: header",
])
def test_bearer_parser_rejects_bad_or_ambiguous_headers(header):
    with pytest.raises(CloudAuthRejected):
        bearer_token(header)


def test_bearer_parser_accepts_single_jwt():
    assert bearer_token("bearer " + TOKEN) == TOKEN


@pytest.mark.parametrize("changes", [
    {"uid": ""}, {"uid": "other/account"}, {"email_verified": False}, {"email": ""},
    {"firebase": {"sign_in_provider": "password"}},
])
def test_principal_requires_verified_google_identity(changes):
    with pytest.raises(CloudAuthRejected):
        principal_from_claims({**GOOGLE_CLAIMS, **changes})


def _fake_sdk(monkeypatch, result):
    sdk = ModuleType("firebase_admin")
    auth = ModuleType("firebase_admin.auth")
    for name in ("InvalidIdTokenError", "ExpiredIdTokenError", "RevokedIdTokenError",
                 "UserDisabledError"):
        setattr(auth, name, type(name, (Exception,), {}))
    calls = []

    def get_app(name):
        calls.append(("get_app", name))
        raise ValueError("not initialized")

    def initialize_app(*, options, name):
        calls.append(("initialize_app", options, name))
        return object()

    def verify_id_token(token, *, app, check_revoked):
        calls.append(("verify", token, check_revoked))
        if isinstance(result, Exception):
            raise result
        return result

    sdk.get_app = get_app
    sdk.initialize_app = initialize_app
    sdk.auth = auth
    auth.verify_id_token = verify_id_token
    monkeypatch.setitem(sys.modules, "firebase_admin", sdk)
    monkeypatch.setitem(sys.modules, "firebase_admin.auth", auth)
    return calls, auth


def test_verifier_uses_exact_project_adc_and_revocation_check(monkeypatch):
    calls, _ = _fake_sdk(monkeypatch, GOOGLE_CLAIMS)
    principal = FirebaseTokenVerifier("lh25-store-20261024").authenticate("Bearer " + TOKEN)
    assert principal.uid == "firebase-uid-1"
    assert principal.email == "owner@example.com"
    assert not hasattr(principal, "role")
    assert ("initialize_app", {"projectId": "lh25-store-20261024"},
            "lh25-cloud-auth-lh25-store-20261024") in calls
    assert ("verify", TOKEN, True) in calls


def test_invalid_or_revoked_token_fails_closed(monkeypatch):
    _, auth = _fake_sdk(monkeypatch, GOOGLE_CLAIMS)
    def reject(*args, **kwargs):
        raise auth.RevokedIdTokenError
    auth.verify_id_token = reject
    with pytest.raises(CloudAuthRejected):
        FirebaseTokenVerifier("lh25-store-20261024").verify(TOKEN)


def test_certificate_or_credential_failure_is_unavailable_not_anonymous(monkeypatch):
    _fake_sdk(monkeypatch, RuntimeError("private diagnostics"))
    with pytest.raises(CloudAuthUnavailable) as error:
        FirebaseTokenVerifier("lh25-store-20261024").verify(TOKEN)
    assert "private diagnostics" not in str(error.value)


def test_project_id_is_mandatory():
    for project_id in ("", "wrong id", "https://firebase.example", "../secrets"):
        with pytest.raises(ValueError):
            FirebaseTokenVerifier(project_id)
