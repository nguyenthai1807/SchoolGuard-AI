from fastapi.testclient import TestClient
import pytest

from schoolguard.cloud_api import create_cloud_api
from schoolguard.cloud_auth import CloudAuthRejected, CloudAuthUnavailable, CloudPrincipal


PROJECT = "lh25-store-20261024"
TERMS = "2026-10-26-cloud"


class FakeVerifier:
    project_id = PROJECT

    def __init__(self, error=None):
        self.error = error

    def authenticate(self, header):
        if self.error:
            raise self.error
        if header != "Bearer signed-firebase-token":
            raise CloudAuthRejected
        return CloudPrincipal("uid-a", "owner@example.com")


class FakeReader:
    project_id = PROJECT

    def __init__(self, profile=None, fail=False):
        self.value = profile
        self.fail = fail

    def profile(self, uid):
        assert uid == "uid-a"
        if self.fail:
            raise RuntimeError("private backend diagnostics")
        return self.value

    def entitlement(self, uid):
        assert uid == "uid-a"
        return None

    def admin_grant(self, uid):
        assert uid == "uid-a"
        return None


def _client(profile=None, verifier=None, reader=None):
    app = create_cloud_api(
        verifier=verifier or FakeVerifier(),
        access_reader=reader or FakeReader(profile),
        required_terms_version=TERMS,
    )
    return TestClient(app)


def test_health_is_not_a_claim_that_customer_api_is_ready():
    response = _client().get("/healthz")
    assert response.json() == {"status": "up", "scope": "auth-probe-only"}
    assert response.headers["cache-control"] == "no-store"


def test_account_probe_requires_authorization_and_cloud_terms():
    client = _client({"acceptedTermsVersion": TERMS})
    assert client.get("/api/cloud/me").status_code == 401
    response = client.get("/api/cloud/me", headers={"Authorization": "Bearer signed-firebase-token"})
    assert response.status_code == 200
    assert response.json() == {"uid": "uid-a", "plan": "free",
                               "can_use_pro": False, "is_admin": False}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert _client({"acceptedTermsVersion": "2026-10-26-browser"}).get(
        "/api/cloud/me", headers={"Authorization": "Bearer signed-firebase-token"}
    ).status_code == 403


def test_auth_or_firestore_outage_fails_closed_without_diagnostics():
    unavailable = _client(verifier=FakeVerifier(CloudAuthUnavailable())).get("/api/cloud/me")
    assert unavailable.status_code == 503
    broken_store = _client(reader=FakeReader(fail=True)).get(
        "/api/cloud/me", headers={"Authorization": "Bearer signed-firebase-token"}
    )
    assert broken_store.status_code == 503
    assert "private backend diagnostics" not in broken_store.text


def test_factory_refuses_cross_project_reader_and_old_terms():
    reader = FakeReader()
    reader.project_id = "some-other-project"
    with pytest.raises(ValueError):
        create_cloud_api(verifier=FakeVerifier(), access_reader=reader,
                         required_terms_version=TERMS)
    with pytest.raises(ValueError):
        create_cloud_api(verifier=FakeVerifier(), access_reader=FakeReader(),
                         required_terms_version="2026-10-26-browser")
