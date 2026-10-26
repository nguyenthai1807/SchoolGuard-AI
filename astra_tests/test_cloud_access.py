from datetime import datetime, timedelta, timezone

import pytest

from schoolguard.cloud_access import CloudAccessDenied, FirestoreAccessReader, resolve_access
from schoolguard.cloud_auth import CloudPrincipal


NOW = datetime(2026, 10, 26, tzinfo=timezone.utc)
TERMS = "2026-10-26-cloud"
PROJECT = "lh25-store-20261024"


class FakeSnapshot:
    def __init__(self, value):
        self.value = value
        self.exists = value is not None

    def to_dict(self):
        return self.value


class FakeClient:
    def __init__(self, data):
        self.data = data
        self.calls = []
        self.project = PROJECT

    def collection(self, name):
        self.name = name
        return self

    def document(self, uid):
        self.calls.append((self.name, uid))
        self.uid = uid
        return self

    def get(self):
        return FakeSnapshot(self.data.get((self.name, self.uid)))


def _access(data, uid="uid-a", **kwargs):
    client = FakeClient(data)
    access = resolve_access(
        CloudPrincipal(uid=uid, email="same@example.com"),
        FirestoreAccessReader(client, project_id=PROJECT),
        required_terms_version=TERMS, at=NOW, **kwargs,
    )
    return access, client.calls


def test_browser_profile_cannot_self_grant_pro_or_admin():
    access, calls = _access({("users", "uid-a"): {
        "acceptedTermsVersion": TERMS, "plan": "pro", "admin": True,
        "email": "same@example.com",
    }})
    assert access.plan == "free" and not access.can_use_pro
    assert not access.is_admin
    assert calls == [("users", "uid-a"), ("cloud_entitlements", "uid-a"),
                     ("cloud_admins", "uid-a")]


def test_missing_or_browser_only_terms_blocks_cloud_access():
    for profile in (None, {"acceptedTermsVersion": "2026-10-26-browser"}):
        with pytest.raises(CloudAccessDenied):
            _access({("users", "uid-a"): profile})
    with pytest.raises(ValueError):
        resolve_access(CloudPrincipal("uid-a", "a@example.com"),
                       FirestoreAccessReader(FakeClient({}), project_id=PROJECT),
                       required_terms_version="2026-10-26-browser", at=NOW)


def test_pro_requires_server_grant_provenance_and_unexpired_time():
    data = {
        ("users", "uid-a"): {"acceptedTermsVersion": TERMS},
        ("cloud_entitlements", "uid-a"): {
            "uid": "uid-a", "status": "active", "plan": "pro",
            "grantSource": "manual_review", "orderId": "order-1",
            "proUntil": NOW + timedelta(days=30),
        },
    }
    access, _ = _access(data)
    assert access.can_use_pro and access.plan == "pro"
    assert access.pro_expires_at == NOW + timedelta(days=30)
    data[("cloud_entitlements", "uid-a")]["proUntil"] = NOW - timedelta(seconds=1)
    expired, _ = _access(data)
    assert expired.plan == "free" and not expired.can_use_pro


@pytest.mark.parametrize("change", [
    {"uid": "uid-b"}, {"status": "suspended"}, {"plan": "vip"},
    {"grantSource": "client"}, {"orderId": ""}, {"proUntil": "tomorrow"},
])
def test_malformed_or_untrusted_grant_fails_closed(change):
    grant = {
        "uid": "uid-a", "status": "active", "plan": "pro",
        "grantSource": "payos_verified", "orderId": "order-1",
        "proUntil": NOW + timedelta(days=30),
    }
    grant.update(change)
    with pytest.raises(CloudAccessDenied):
        _access({
            ("users", "uid-a"): {"acceptedTermsVersion": TERMS},
            ("cloud_entitlements", "uid-a"): grant,
        })


def test_admin_needs_separate_mfa_and_matching_server_grant():
    data = {
        ("users", "uid-a"): {"acceptedTermsVersion": TERMS},
        ("cloud_admins", "uid-a"): {"uid": "uid-a", "enabled": True},
    }
    ordinary, _ = _access(data)
    assert not ordinary.is_admin and not ordinary.can_use_pro
    verified, _ = _access(data, mfa_verified=True)
    assert verified.is_admin and verified.can_use_pro
    data[("cloud_admins", "uid-a")]["uid"] = "uid-b"
    with pytest.raises(CloudAccessDenied):
        _access(data, mfa_verified=True)


def test_same_email_does_not_grant_another_uid_access():
    data = {
        ("users", "uid-a"): {"acceptedTermsVersion": TERMS},
        ("cloud_entitlements", "uid-a"): {
            "uid": "uid-a", "status": "active", "plan": "pro",
            "grantSource": "manual_review", "orderId": "order-1",
            "proUntil": NOW + timedelta(days=30),
        },
        ("users", "uid-b"): {"acceptedTermsVersion": TERMS},
    }
    access, calls = _access(data, uid="uid-b")
    assert access.plan == "free"
    assert all(uid == "uid-b" for _, uid in calls)


def test_document_path_is_bounded_to_single_uid():
    client = FakeClient({})
    with pytest.raises(CloudAccessDenied):
        FirestoreAccessReader(client, project_id=PROJECT).profile("other/account")
    assert client.calls == []


def test_firestore_reader_refuses_a_different_project():
    with pytest.raises(ValueError):
        FirestoreAccessReader(FakeClient({}), project_id="another-project")
