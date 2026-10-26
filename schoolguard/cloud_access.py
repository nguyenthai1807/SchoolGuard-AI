"""Read-only cloud entitlement policy; no live Firebase writes or migration.

The browser-created /users/{uid} profile proves terms acceptance only. Pro and
Admin grants live in separate server-owned collections denied by client rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from .cloud_auth import CloudPrincipal


class CloudAccessDenied(Exception):
    """No usable account or a malformed entitlement. Do not expose details."""


@dataclass(frozen=True)
class CloudAccess:
    uid: str
    plan: str
    is_admin: bool
    pro_expires_at: datetime | None

    @property
    def can_use_pro(self) -> bool:
        return self.is_admin or self.plan == "pro"


class FirestoreAccessReader:
    """Read only the three documents belonging to one verified Firebase UID.

    The injected Firestore server client uses ADC/IAM and bypasses client rules.
    This class intentionally offers no method to create or approve grants.
    """

    def __init__(self, client, *, project_id: str):
        if not project_id or getattr(client, "project", None) != project_id:
            raise ValueError("Firestore client must match the verified Firebase project")
        self.client = client
        self.project_id = project_id

    def _get(self, collection: str, uid: str) -> dict | None:
        if not isinstance(uid, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", uid):
            raise CloudAccessDenied
        snapshot = self.client.collection(collection).document(uid).get()
        return snapshot.to_dict() if snapshot.exists else None

    def profile(self, uid: str) -> dict | None:
        return self._get("users", uid)

    def entitlement(self, uid: str) -> dict | None:
        return self._get("cloud_entitlements", uid)

    def admin_grant(self, uid: str) -> dict | None:
        return self._get("cloud_admins", uid)


def resolve_access(principal: CloudPrincipal, reader: FirestoreAccessReader,
                   *, required_terms_version: str, mfa_verified: bool = False,
                   at: datetime | None = None) -> CloudAccess:
    """Default Free only after terms; Pro/Admin require server-owned evidence."""
    if not isinstance(required_terms_version, str) or not required_terms_version.endswith("-cloud"):
        raise ValueError("A cloud-specific terms version is required")
    now = at or datetime.now(timezone.utc)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Use a timezone-aware clock")
    uid = principal.uid
    profile = reader.profile(uid)
    if not isinstance(profile, dict) or profile.get("acceptedTermsVersion") != required_terms_version:
        raise CloudAccessDenied

    entitlement = reader.entitlement(uid)
    plan = "free"
    expires = None
    if entitlement is not None:
        if (not isinstance(entitlement, dict) or entitlement.get("uid") != uid
                or entitlement.get("status") != "active"):
            raise CloudAccessDenied
        requested_plan = entitlement.get("plan")
        if requested_plan == "pro":
            expiry = entitlement.get("proUntil")
            if (entitlement.get("grantSource") not in {"manual_review", "payos_verified"}
                    or not isinstance(entitlement.get("orderId"), str)
                    or not entitlement["orderId"]
                    or not isinstance(expiry, datetime)
                    or expiry.tzinfo is None or expiry.utcoffset() is None):
                raise CloudAccessDenied
            if expiry > now:
                plan = "pro"
                expires = expiry
        elif requested_plan != "free":
            raise CloudAccessDenied

    admin_grant = reader.admin_grant(uid)
    is_admin = False
    if admin_grant is not None:
        if (not isinstance(admin_grant, dict) or admin_grant.get("uid") != uid
                or type(admin_grant.get("enabled")) is not bool):
            raise CloudAccessDenied
        # Identity token alone is insufficient for administrative operations.
        # A future independent MFA challenge must supply mfa_verified.
        is_admin = admin_grant["enabled"] and mfa_verified is True
    return CloudAccess(uid=uid, plan=plan, is_admin=is_admin, pro_expires_at=expires)
