"""Complimentary Pro grants for named team members on the local LH25 server.

Pending grants are redeemed only after Google verifies the email. These grants
are not orders, payments, or admin privileges.
"""

import re

from .db import now


EMAIL_PATTERN = re.compile(r"^[^\s@]+@[^\s@]+\.[^\s@]+$")


def normalize_email(email):
    value = email.strip().lower()
    if not EMAIL_PATTERN.fullmatch(value) or len(value) > 254:
        raise ValueError("Email không hợp lệ")
    return value


def _activate(conn, user_id):
    timestamp = now()
    conn.execute(
        "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
        "VALUES(?,'pro_local',NULL,'team_grant',?) "
        "ON CONFLICT(user_id) DO UPDATE SET plan='pro_local',expires_at=NULL,"
        "source='team_grant',updated_at=excluded.updated_at",
        (user_id, timestamp),
    )
    return timestamp


def provision(db, email):
    """Queue a verified-Google-email grant, or activate an existing Google user."""
    email = normalize_email(email)
    with db.connect() as conn:
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT u.id,u.role,g.subject FROM customer_profiles p "
            "JOIN users u ON u.id=p.user_id "
            "LEFT JOIN google_identities g ON g.user_id=u.id "
            "WHERE lower(p.email)=?",
            (email,),
        ).fetchone()
        if row and row["role"] == "admin":
            return "already_admin"
        if row and not row["subject"]:
            return "unlinked_account"
        grant = conn.execute(
            "SELECT applied_user_id FROM team_pro_grants WHERE email=?", (email,)
        ).fetchone()
        if grant and grant["applied_user_id"] is not None:
            return "already_granted"
        conn.execute(
            "INSERT OR IGNORE INTO team_pro_grants(email,created_at) VALUES(?,?)",
            (email, now()),
        )
        if row:
            applied_at = _activate(conn, row["id"])
            conn.execute(
                "UPDATE team_pro_grants SET applied_user_id=?,applied_at=? "
                "WHERE email=?",
                (row["id"], applied_at, email),
            )
            return "activated"
        return "pending_google_login"


def redeem_verified_google_email(conn, email, user_id):
    """Called inside the Google sign-in transaction, after token verification."""
    email = normalize_email(email)
    profile = conn.execute(
        "SELECT 1 FROM customer_profiles WHERE user_id=? AND lower(email)=?",
        (user_id, email),
    ).fetchone()
    if not profile:
        return False
    grant = conn.execute(
        "SELECT applied_user_id FROM team_pro_grants WHERE email=?", (email,)
    ).fetchone()
    if not grant or grant["applied_user_id"] is not None:
        return False
    applied_at = _activate(conn, user_id)
    conn.execute(
        "UPDATE team_pro_grants SET applied_user_id=?,applied_at=? "
        "WHERE email=? AND applied_user_id IS NULL",
        (user_id, applied_at, email),
    )
    return True
