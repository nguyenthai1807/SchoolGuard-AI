"""Free/Pro entitlements with expiry; payOS activates paid subscriptions."""

from datetime import datetime, timedelta, timezone

FREE_VIDEO_LIMIT = 3
FREE_VIDEO_SECONDS = 120
FREE_UPLOAD_BYTES = 100 * 1024 * 1024
PRO_VIDEO_LIMIT = 60
PRO_VIDEO_SECONDS = 10 * 60
PRO_UPLOAD_BYTES = 500 * 1024 * 1024
PRO_WEBCAM_SECONDS_PER_DAY = 5 * 60 * 60
PRO_PRICE_VND = 29_000
PRO_DAYS = 30
VIETNAM = timezone(timedelta(hours=7), "Asia/Ho_Chi_Minh")


def month_start_utc(at=None):
    local = (at or datetime.now(timezone.utc)).astimezone(VIETNAM)
    return local.replace(day=1, hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


def next_month_utc(at=None):
    local = (at or datetime.now(timezone.utc)).astimezone(VIETNAM)
    year, month = (local.year + 1, 1) if local.month == 12 else (local.year, local.month + 1)
    return datetime(year, month, 1, tzinfo=VIETNAM).astimezone(timezone.utc)


def usage_day(at=None):
    return (at or datetime.now(timezone.utc)).astimezone(VIETNAM).date().isoformat()


def entitlement(db, current, at=None):
    now = at or datetime.now(timezone.utc)
    if current["role"] == "admin":
        return {"plan": "admin", "expires_at": None, "video_limit": None,
                "video_seconds": None, "upload_bytes": None, "webcam": True, "faces": True,
                "webcam_seconds_per_day": None}
    row = db.one("SELECT plan,expires_at FROM subscriptions WHERE user_id=?", (current["id"],))
    active = row and row["plan"] == "pro_local" and (
        row["expires_at"] is None or datetime.fromisoformat(row["expires_at"]) > now
    )
    return {"plan": "pro_local" if active else "free",
            "expires_at": row["expires_at"] if active else None,
            "video_limit": PRO_VIDEO_LIMIT if active else FREE_VIDEO_LIMIT,
            "video_seconds": PRO_VIDEO_SECONDS if active else FREE_VIDEO_SECONDS,
            "upload_bytes": PRO_UPLOAD_BYTES if active else FREE_UPLOAD_BYTES,
            "webcam": bool(active), "faces": bool(active),
            "webcam_seconds_per_day": PRO_WEBCAM_SECONDS_PER_DAY if active else 0}


def plan_status(db, current):
    policy = entitlement(db, current)
    start = month_start_utc()
    used = db.one(
        "SELECT count(*) n FROM jobs WHERE user_id=? AND quota_charged=1 "
        "AND created_at>=? AND status!='failed'",
        (current["id"], start.isoformat()),
    )["n"]
    pending = db.one(
        "SELECT id,status,created_at,amount_vnd,checkout_url,payment_order_code FROM orders WHERE user_id=? "
        "AND status IN ('requested','transfer_reported','initiating') "
        "ORDER BY created_at DESC LIMIT 1", (current["id"],),
    )
    webcam_usage = db.one(
        "SELECT seconds FROM daily_camera_usage WHERE user_id=? AND day=?",
        (current["id"], usage_day()),
    )
    return {**policy, "video_used": used, "video_reset_at": next_month_utc().isoformat(),
            "webcam_used_seconds_today": round(webcam_usage["seconds"], 1) if webcam_usage else 0,
            "pending_order": pending, "pro_price_vnd": PRO_PRICE_VND, "pro_days": PRO_DAYS}


def pro_expiry(existing):
    now = datetime.now(timezone.utc)
    if existing and existing["plan"] == "pro_local" and existing["expires_at"]:
        previous = datetime.fromisoformat(existing["expires_at"])
        if previous > now:
            now = previous
    return (now + timedelta(days=PRO_DAYS)).isoformat()
