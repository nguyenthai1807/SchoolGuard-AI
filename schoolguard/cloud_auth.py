"""Firebase identity boundary for the future LH25 cloud API.

This module does not grant Admin or Pro. Entitlements must be loaded from a
durable server-side store by the verified Firebase UID after this step.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_PROJECT_ID = re.compile(r"[a-z][a-z0-9-]{4,28}[a-z0-9]\Z")
_JWT = re.compile(r"[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\Z")
_DOCUMENT_SAFE_UID = re.compile(r"[A-Za-z0-9_-]{1,128}\Z")


class CloudAuthRejected(Exception):
    """Credential is absent, invalid, expired, revoked or not Google sign-in."""


class CloudAuthUnavailable(Exception):
    """Server cannot currently verify credentials; fail closed."""


@dataclass(frozen=True)
class CloudPrincipal:
    uid: str
    email: str  # Display/contact only, never an authorization or migration key.


def bearer_token(header: str | None) -> str:
    """Parse a single bounded Authorization header without logging its value."""
    if not header or len(header) > 8200:
        raise CloudAuthRejected
    scheme, separator, token = header.partition(" ")
    if separator != " " or scheme.lower() != "bearer" or not 20 <= len(token) <= 8192:
        raise CloudAuthRejected
    if not _JWT.fullmatch(token):
        raise CloudAuthRejected
    return token


def principal_from_claims(claims: object) -> CloudPrincipal:
    """Accept only a verified Google-backed Firebase account, never role claims."""
    if not isinstance(claims, dict):
        raise CloudAuthRejected
    uid = claims.get("uid")
    email = claims.get("email")
    firebase = claims.get("firebase")
    if (not isinstance(uid, str) or not _DOCUMENT_SAFE_UID.fullmatch(uid)
            or not isinstance(email, str) or not email or len(email) > 320
            or claims.get("email_verified") is not True
            or not isinstance(firebase, dict)
            or firebase.get("sign_in_provider") != "google.com"):
        raise CloudAuthRejected
    return CloudPrincipal(uid=uid, email=email)


class FirebaseTokenVerifier:
    """Production adapter using ADC on Cloud Run, never a bundled JSON key."""

    def __init__(self, project_id: str):
        if not isinstance(project_id, str) or not _PROJECT_ID.fullmatch(project_id):
            raise ValueError("A valid Firebase project ID is required")
        self.project_id = project_id

    def verify(self, token: str) -> CloudPrincipal:
        try:
            import firebase_admin
            from firebase_admin import auth
        except ImportError as exc:
            raise CloudAuthUnavailable from exc

        name = "lh25-cloud-auth-" + self.project_id
        try:
            try:
                app = firebase_admin.get_app(name)
            except ValueError:
                try:
                    app = firebase_admin.initialize_app(
                        options={"projectId": self.project_id}, name=name
                    )
                except ValueError:
                    # Another worker thread may have initialized the same app.
                    app = firebase_admin.get_app(name)
            claims = auth.verify_id_token(token, app=app, check_revoked=True)
        except (auth.InvalidIdTokenError, auth.ExpiredIdTokenError,
                auth.RevokedIdTokenError, auth.UserDisabledError) as exc:
            raise CloudAuthRejected from exc
        except Exception as exc:
            # Certificate lookup, ADC and Firebase outages must never become
            # a successful or anonymous session. Keep details out of HTTP.
            raise CloudAuthUnavailable from exc
        return principal_from_claims(claims)

    def authenticate(self, authorization_header: str | None) -> CloudPrincipal:
        return self.verify(bearer_token(authorization_header))
