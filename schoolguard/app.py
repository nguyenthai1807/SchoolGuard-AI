import base64
import csv
import ipaddress
import io
import json
import mimetypes
import os
import re
import sqlite3
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import ExitStack, asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote, urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

# Windows MIME registries may omit WebP; Starlette's static responses use this map.
mimetypes.add_type("image/webp", ".webp")

from .auth import bootstrap, hash_password, make_session, token_hash, verify_password
from .billing_notifications import BillingNotifications, enqueue_receipts
from .model_catalog import MODELS, catalog, requires_pro
from .commerce import (PayOSGateway, SmtpEmailSender, hash_email_token,
                       valid_public_url)
from .config import Settings
from .google_login import install_google_login
from .db import Database, now, public_job
from .detector import PersonDetector
from .faces import FaceLedger, FaceRecognizer, models_ready
from .fire import FireDetector
from .live import LiveAnalyzer
from .media import Reader, index_dataset, jpeg, metadata
from .network_camera import NetworkCamera, camera_credentials, validate_camera_url
from .plans import (PRO_PRICE_VND, entitlement, month_start_utc, plan_status, pro_expiry, usage_day)
from .schemas import (COCO_DETECTION_MODELS, POSE_MODELS, AlertUpdate, CameraView, CustomerProfile, DemoPick, JobRequest, Login,
                      ManualPaymentLink, PaymentConfirmation, PublicRegistration, UserCreate,
                      VerifyEmailToken)
from .telegram import TelegramNotifier
from .telegram_link import TelegramLinker, TelegramUnavailable, recipient_for
from .worker import Worker
from .weapons import WeaponDetector


def create_app(settings=None, detector_factory=None, fire_factory=None, face_factory=None,
               email_sender=None, payment_gateway=None, weapon_factory=None):
    settings = settings or Settings()
    # Cloud Run instances have disposable local filesystems. Until the SQLite,
    # uploads, evidence and worker state have durable cloud adapters, starting
    # this local-first server there would put customer data at risk.
    if os.environ.get("K_SERVICE") or os.environ.get("LH25_DEPLOYMENT_TARGET", "").lower() == "cloud":
        raise RuntimeError(
            "LH25 cloud backend is not ready: migrate SQLite, media and worker "
            "state to durable services before starting the original FastAPI app."
        )
    if settings.google_only and (not settings.google_client_id or not settings.google_admin_subjects):
        raise RuntimeError("Google-only cần LH25_GOOGLE_CLIENT_ID và LH25_GOOGLE_ADMIN_SUBS trước khi bật.")
    email_sender = email_sender or SmtpEmailSender()
    payment_gateway = payment_gateway or PayOSGateway()
    if settings.email_verification_required:
        if not email_sender.available or not valid_public_url(settings.public_base_url):
            raise RuntimeError("Xác minh email cần SMTP và tên miền HTTPS cố định.")
    if settings.payment_enabled:
        if (not settings.email_verification_required or not payment_gateway.available
                or not valid_public_url(settings.public_base_url)):
            raise RuntimeError("Thanh toán cần email đã xác minh, payOS và tên miền HTTPS cố định.")
    settings.runtime.mkdir(parents=True, exist_ok=True)
    db = Database(settings.runtime / "schoolguard.sqlite3")
    db.execute("CREATE TABLE IF NOT EXISTS daily_camera_usage ("
               "user_id INTEGER NOT NULL REFERENCES users(id), day TEXT NOT NULL, "
               "seconds REAL NOT NULL DEFAULT 0, PRIMARY KEY(user_id,day))")
    worker = Worker(db, settings,
                    **({"detector_factory": detector_factory} if detector_factory else {}),
                    **({"fire_factory": fire_factory} if fire_factory else {}),
                    **({"face_factory": face_factory} if face_factory else {}),
                    **({"weapon_factory": weapon_factory} if weapon_factory else {}))
    live_sessions = {}
    live_lock = threading.Lock()
    notifier = TelegramNotifier()
    receipts = BillingNotifications(db, email_sender, notifier)
    telegram_linker = TelegramLinker(db, getattr(notifier, "token", ""))
    telegram_retry_lock = threading.Lock()
    attempts = defaultdict(deque)
    registrations = defaultdict(deque)
    email_checks = defaultdict(deque)
    attempts_lock = threading.Lock()
    dummy_hash = hash_password(secrets.token_urlsafe(20))

    @asynccontextmanager
    async def lifespan(app):
        bootstrap(db, settings.runtime)
        # Uploaded media moves with runtime. Repair only missing local upload paths.
        for row in db.all("SELECT id,path FROM sources WHERE split='uploaded'"):
            old = Path(row["path"])
            moved = settings.runtime / "uploads" / old.name
            if not old.exists() and moved.is_file():
                db.execute(
                    "UPDATE sources SET path=? WHERE id=?", (str(moved.resolve()), row["id"])
                )
        index_dataset(db, settings.data_root)
        if settings.start_worker:
            worker.start()
            receipts.start()
        yield
        with live_lock:
            for session in live_sessions.values():
                if session.get("source"):
                    session["source"].close()
            live_sessions.clear()
        worker.close()
        receipts.close()

    app = FastAPI(title="LH25 · Home Monitor", version="0.2.0", lifespan=lifespan)
    app.state.db = db
    app.state.worker = worker
    app.state.settings = settings
    app.state.billing_notifications = receipts
    app.state.live_sessions = live_sessions
    app.state.telegram_linker = telegram_linker
    app.state.email_sender = email_sender
    app.state.payment_gateway = payment_gateway
    install_google_login(app, db, settings)
    # Quick Tunnel terminates HTTPS at Cloudflare and forwards to localhost.
    # The wildcard is limited to Cloudflare's temporary testing domain; arbitrary
    # Host headers remain rejected by TrustedHostMiddleware.
    allowed_hosts = ["127.0.0.1", "localhost", "testserver", "[::1]", "*.trycloudflare.com"]
    if valid_public_url(settings.public_base_url):
        allowed_hosts.append(urlparse(settings.public_base_url).hostname)
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=allowed_hosts,
    )

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return Response("Origin refused", status_code=403)
        result = await call_next(request)
        result.headers["X-Content-Type-Options"] = "nosniff"
        # GIS needs the local HTTP origin as referrer for its popup/iframe checks.
        # Keep the stricter policy for public HTTPS and when Google is disabled.
        local_google = bool(settings.google_client_id) and request.url.hostname in {
            "127.0.0.1", "localhost"
        }
        result.headers["Referrer-Policy"] = (
            "no-referrer-when-downgrade" if local_google else "same-origin"
        )
        result.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
        if settings.google_client_id:
            result.headers["Content-Security-Policy"] = (
                "default-src 'self'; img-src 'self' blob: data: https://*.googleusercontent.com; "
                "media-src 'self' blob:; style-src 'self' https://accounts.google.com/gsi/style; "
                "script-src 'self' https://accounts.google.com/gsi/client; "
                "frame-src https://accounts.google.com/gsi/; connect-src 'self' https://accounts.google.com/gsi/; "
                "frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
            )
            result.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        if request.url.path.startswith("/api"):
            result.headers["Cache-Control"] = "no-store"
        return result

    def user(request: Request):
        token = request.cookies.get("sg_session", "")
        row = db.one(
            "SELECT u.id,u.username,u.role FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token=? AND s.expires>?",
            (token_hash(token), time.time()),
        )
        if not row:
            raise HTTPException(401, "Vui lòng đăng nhập.")
        identity = db.one("SELECT subject FROM google_identities WHERE user_id=?", (row["id"],))
        if settings.google_only and not identity:
            raise HTTPException(401, "Hãy đăng nhập bằng Google để tiếp tục.")
        if identity:
            row["role"] = "admin" if identity["subject"] in settings.google_admin_subjects else "operator"
        return row

    def operator(current=Depends(user)):
        if current["role"] not in {"operator", "admin"}:
            raise HTTPException(403, "Cần quyền operator hoặc admin.")
        return current

    def admin(current=Depends(user)):
        if current["role"] != "admin":
            raise HTTPException(403, "Cần quyền admin.")
        return current

    def notification_items(user_id):
        # Read from the source of truth so a completed job or approved payment
        # appears even if the browser was closed when it happened.
        jobs = db.all(
            "SELECT 'job:' || j.id AS id,j.id AS entity_id,j.status,s.name AS subject,"
            "COALESCE(j.finished_at,j.created_at) AS created_at,r.read_at "
            "FROM jobs j JOIN sources s ON s.id=j.source_id "
            "LEFT JOIN notification_reads r ON r.user_id=j.user_id AND r.item_id='job:' || j.id "
            "WHERE j.user_id=? AND j.source_id!=j.id AND j.status IN ('completed','failed') "
            "ORDER BY created_at DESC LIMIT 50", (user_id,),
        )
        orders = db.all(
            "SELECT 'order:' || o.id AS id,o.id AS entity_id,o.status,'' AS subject,"
            "COALESCE(o.resolved_at,o.created_at) AS created_at,r.read_at "
            "FROM orders o LEFT JOIN notification_reads r "
            "ON r.user_id=o.user_id AND r.item_id='order:' || o.id "
            "WHERE o.user_id=? AND o.status='activated' ORDER BY created_at DESC LIMIT 50",
            (user_id,),
        )
        items = []
        for row in jobs:
            completed = row["status"] == "completed"
            items.append({
                "id": row["id"], "type": "video_completed" if completed else "video_failed",
                "title": "Đã phân tích xong video" if completed else "Phân tích video thất bại",
                "message": row["subject"], "href": "#job/" + row["entity_id"],
                "created_at": row["created_at"], "read": bool(row["read_at"]),
            })
        for row in orders:
            items.append({
                "id": row["id"], "type": "pro_activated",
                "title": "Gói Pro đã được kích hoạt",
                "message": "Bạn có thể sử dụng các tính năng Pro trong LH25.",
                "href": "#plan", "created_at": row["created_at"],
                "read": bool(row["read_at"]),
            })
        return sorted(items, key=lambda item: item["created_at"], reverse=True)[:50]

    @app.get("/api/notifications")
    def notifications(current=Depends(user)):
        items = notification_items(current["id"])
        return {"items": items, "unread": sum(not item["read"] for item in items)}

    @app.post("/api/notifications/read-all")
    def read_all_notifications(current=Depends(user)):
        items = notification_items(current["id"])
        with db.connect() as conn:
            for item in items:
                conn.execute(
                    "INSERT OR IGNORE INTO notification_reads(user_id,item_id,read_at) VALUES(?,?,?)",
                    (current["id"], item["id"], now()),
                )
        return {"unread": 0}

    @app.post("/api/notifications/{item_id}/read")
    def read_notification(item_id: str, current=Depends(user)):
        if item_id not in {item["id"] for item in notification_items(current["id"])}:
            raise HTTPException(404, "Không tìm thấy thông báo.")
        db.execute(
            "INSERT OR IGNORE INTO notification_reads(user_id,item_id,read_at) VALUES(?,?,?)",
            (current["id"], item_id, now()),
        )
        return {"read": True}

    def require_recipient(current):
        # The original local admin can still run demos with the legacy .env chat.
        if current["role"] == "admin" and current["username"] == "admin":
            return
        require_verified_email(current)
        if not db.one("SELECT user_id FROM customer_profiles WHERE user_id=?",
                      (current["id"],)):
            raise HTTPException(409, "Điền thông tin khách hàng ở mục Telegram trước khi phân tích.")
        telegram_state = telegram_linker.status(current["id"])
        if not telegram_state["bot_configured"] or not telegram_state["linked"]:
            raise HTTPException(409, "Kết nối Telegram ở mục Telegram trước khi phân tích.")

    def secure_cookie(request):
        return request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https"

    def rate_key(request):
        key = request.client.host if request.client else "local"
        host = request.headers.get("host", "").split(":", 1)[0].lower()
        if key in {"127.0.0.1", "::1"} and host.endswith(".trycloudflare.com"):
            try:
                return str(ipaddress.ip_address(request.headers.get("cf-connecting-ip", "")))
            except ValueError:
                pass
        return key

    def require_verified_email(current):
        if not settings.email_verification_required or current["role"] == "admin":
            return
        row = db.one("SELECT verified_at FROM email_verifications WHERE user_id=?", (current["id"],))
        if not row or not row["verified_at"]:
            raise HTTPException(409, "Xác minh email ở mục Gói của tôi trước khi sử dụng LH25.")

    def send_verification(user_id, email):
        if not email_sender.available or not valid_public_url(settings.public_base_url):
            raise HTTPException(503, "Chưa cấu hình dịch vụ gửi email và tên miền HTTPS cố định.")
        raw = secrets.token_urlsafe(32)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute("SELECT sent_at FROM email_verifications WHERE user_id=?",
                                    (user_id,)).fetchone()
            if previous and previous["sent_at"] and previous["sent_at"] > time.time() - 60:
                raise HTTPException(429, "Vui lòng đợi một phút trước khi gửi lại email.")
            conn.execute(
                "INSERT INTO email_verifications(user_id,email,token_hash,expires_at,sent_at,verified_at) "
                "VALUES(?,?,?,?,?,NULL) ON CONFLICT(user_id) DO UPDATE SET email=excluded.email,"
                "token_hash=excluded.token_hash,expires_at=excluded.expires_at,"
                "sent_at=excluded.sent_at,verified_at=NULL",
                (user_id, email, hash_email_token(raw), time.time() + 1800, time.time()),
            )
        url = settings.public_base_url.rstrip("/") + "/verify-email#token=" + quote(raw)
        try:
            email_sender.send_verification(email, url)
        except Exception as exc:
            db.execute("UPDATE email_verifications SET token_hash=NULL,expires_at=NULL,sent_at=NULL "
                       "WHERE user_id=? AND token_hash=?", (user_id, hash_email_token(raw)))
            raise HTTPException(503, "Không gửi được email xác minh. Thử lại sau.") from exc
        db.audit(user_id, "email_verification_sent", str(user_id))
        return {"sent": True, "expires_in_seconds": 1800}

    def source(ident, current):
        row = db.one("SELECT * FROM sources WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404, "Không tìm thấy nguồn video.")
        if current["role"] != "admin" and not db.one(
            "SELECT source_id FROM source_ownership WHERE source_id=? AND user_id=?",
            (ident, current["id"]),
        ):
            raise HTTPException(404, "Không tìm thấy nguồn video.")
        path = Path(row["path"]).resolve()
        allowed = [
            settings.data_root.resolve(),
            (settings.runtime / "uploads").resolve(),
            (settings.runtime / "event-data").resolve(),
        ]
        if not any(path.is_relative_to(root) for root in allowed):
            raise HTTPException(403, "Nguồn nằm ngoài thư mục dữ liệu được cấu hình.")
        if not path.exists():
            raise HTTPException(404, "Dữ liệu không còn ở đường dẫn đã đăng ký.")
        return row

    def job(ident, current):
        row = db.one(
            "SELECT j.*,s.name source_name FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.id=?",
            (ident,),
        )
        if not row:
            raise HTTPException(404, "Không tìm thấy tác vụ.")
        if current["role"] != "admin" and row["user_id"] != current["id"]:
            raise HTTPException(404, "Không tìm thấy tác vụ.")
        return public_job(row)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.2.0", "product": "LH25"}

    def local_payos_pilot(request: Request):
        return (not settings.payment_enabled and payment_gateway.available
                and str(request.base_url).rstrip("/") == "http://localhost:8770")

    @app.get("/api/commerce/status")
    def commerce_status(request: Request):
        return {"email_required": settings.email_verification_required,
                "payment_enabled": settings.payment_enabled,
                "pilot_checkout_enabled": local_payos_pilot(request)}

    @app.post("/api/login")
    def login(payload: Login, request: Request, response: Response):
        if settings.google_only:
            raise HTTPException(403, "Chế độ này chỉ cho phép đăng nhập Google.")
        key = rate_key(request)
        with attempts_lock:
            queue = attempts[key]
            while queue and queue[0] < time.monotonic() - 60:
                queue.popleft()
            if len(queue) >= 8:
                raise HTTPException(429, "Thử lại sau một phút.")
            queue.append(time.monotonic())
        row = db.one("SELECT * FROM users WHERE username=?", (payload.username,))
        valid = verify_password(payload.password, row["password"] if row else dummy_hash)
        if not row or not valid:
            raise HTTPException(401, "Tên đăng nhập hoặc mật khẩu không đúng.")
        token = make_session(db, row["id"])
        response.set_cookie("sg_session", token, httponly=True, samesite="strict",
                            secure=secure_cookie(request), max_age=8 * 3600)
        db.audit(row["id"], "login", str(row["id"]))
        return {"id": row["id"], "username": row["username"], "role": row["role"]}

    @app.post("/api/register", status_code=201)
    def register(payload: PublicRegistration, request: Request, response: Response):
        if settings.google_only:
            raise HTTPException(403, "Hãy đăng ký bằng tài khoản Google trên trang này.")
        key = rate_key(request)
        with attempts_lock:
            queue = registrations[key]
            while queue and queue[0] < time.monotonic() - 3600:
                queue.popleft()
            if len(queue) >= 3:
                raise HTTPException(429, "Máy này đã tạo nhiều tài khoản. Thử lại sau một giờ.")
            queue.append(time.monotonic())
        username = payload.username.lower()
        email = payload.email.lower()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM users WHERE lower(username)=?", (username,)).fetchone():
                raise HTTPException(409, "Tên đăng nhập đã được sử dụng.")
            if conn.execute("SELECT 1 FROM customer_profiles WHERE lower(email)=?", (email,)).fetchone():
                raise HTTPException(409, "Email đã được sử dụng.")
            cursor = conn.execute(
                "INSERT INTO users(username,password,role) VALUES(?,?,'operator')",
                (username, hash_password(payload.password)),
            )
            ident = cursor.lastrowid
            conn.execute(
                "INSERT INTO customer_profiles(user_id,display_name,email,phone,updated_at) "
                "VALUES(?,?,?,'',?)", (ident, payload.display_name, email, now()),
            )
            conn.execute(
                "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
                "VALUES(?,'free',NULL,'registration',?)", (ident, now()),
            )
        token = make_session(db, ident)
        response.set_cookie("sg_session", token, httponly=True, samesite="strict",
                            secure=secure_cookie(request), max_age=8 * 3600)
        db.audit(ident, "register_free", str(ident), "consent_v1")
        email_sent = False
        if settings.email_verification_required:
            try:
                send_verification(ident, email)
                email_sent = True
            except HTTPException:
                # Account remains usable for login/resend, but analysis stays gated.
                pass
        return {"id": ident, "username": username, "role": "operator", "plan": "free",
                "email_verification_required": settings.email_verification_required,
                "email_sent": email_sent}

    @app.post("/api/logout")
    def logout(request: Request, response: Response, current=Depends(user)):
        db.execute(
            "DELETE FROM sessions WHERE token=?",
            (token_hash(request.cookies.get("sg_session", "")),),
        )
        response.delete_cookie("sg_session")
        return {"ok": True}

    @app.get("/api/me")
    def me(current=Depends(user)):
        profile = db.one("SELECT display_name,email FROM customer_profiles WHERE user_id=?", (current["id"],))
        return {**current, "display_name": profile["display_name"] if profile else None,
                "email": profile["email"] if profile else None}

    @app.get("/api/me/google-identity")
    def my_google_identity(current=Depends(user)):
        identity = db.one("SELECT subject FROM google_identities WHERE user_id=?", (current["id"],))
        return {"linked": bool(identity), "subject": identity["subject"] if identity else None}

    @app.get("/api/me/plan")
    def my_plan(current=Depends(user)):
        return plan_status(db, current)

    @app.get("/api/me/commerce")
    def my_commerce(request: Request, current=Depends(user)):
        profile = db.one("SELECT email FROM customer_profiles WHERE user_id=?", (current["id"],))
        verified = db.one("SELECT email,verified_at FROM email_verifications WHERE user_id=?",
                          (current["id"],))
        manual_ready = bool(settings.manual_bank_name and settings.manual_bank_account
                            and settings.manual_bank_recipient) and not settings.payment_enabled
        return {"email": profile["email"] if profile else "",
                "email_required": settings.email_verification_required,
                "email_verified": current["role"] == "admin" or bool(
                    profile and verified and verified["email"] == profile["email"]
                    and verified["verified_at"]),
                "payment_enabled": settings.payment_enabled,
                "pilot_checkout_enabled": local_payos_pilot(request),
                "manual_transfer": {"bank": settings.manual_bank_name,
                                    "account": settings.manual_bank_account,
                                    "recipient": settings.manual_bank_recipient} if manual_ready else None}

    @app.post("/api/email/resend")
    def resend_email(current=Depends(user)):
        profile = db.one("SELECT email FROM customer_profiles WHERE user_id=?", (current["id"],))
        if not profile:
            raise HTTPException(409, "Điền email liên hệ trước khi xác minh.")
        verified = db.one("SELECT email,verified_at FROM email_verifications WHERE user_id=?",
                          (current["id"],))
        if verified and verified["email"] == profile["email"] and verified["verified_at"]:
            return {"sent": False, "already_verified": True}
        return send_verification(current["id"], profile["email"])

    @app.post("/api/email/verify")
    def verify_email(payload: VerifyEmailToken, request: Request):
        key = rate_key(request)
        with attempts_lock:
            queue = email_checks[key]
            while queue and queue[0] < time.monotonic() - 60:
                queue.popleft()
            if len(queue) >= 20:
                raise HTTPException(429, "Quá nhiều lần kiểm tra. Thử lại sau một phút.")
            queue.append(time.monotonic())
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT e.user_id,e.email,p.email profile_email FROM email_verifications e "
                "JOIN customer_profiles p ON p.user_id=e.user_id "
                "WHERE e.token_hash=? AND e.expires_at>? AND e.verified_at IS NULL",
                (hash_email_token(payload.token), time.time()),
            ).fetchone()
            if not row or row["email"] != row["profile_email"]:
                raise HTTPException(400, "Liên kết xác minh đã hết hạn hoặc không hợp lệ.")
            conn.execute(
                "UPDATE email_verifications SET token_hash=NULL,expires_at=NULL,verified_at=? "
                "WHERE user_id=?", (now(), row["user_id"]),
            )
        db.audit(row["user_id"], "email_verified", str(row["user_id"]))
        return {"verified": True}

    @app.post("/api/orders/pro-local", status_code=201)
    def request_pro(request: Request, current=Depends(operator)):
        if settings.payment_enabled:
            raise HTTPException(409, "Thanh toán tự động đã bật; dùng nút Thanh toán Pro Local.")
        require_verified_email(current)
        if not db.one("SELECT 1 FROM customer_profiles WHERE user_id=?", (current["id"],)):
            raise HTTPException(409, "Cần nhập thông tin liên hệ trước khi yêu cầu Pro.")
        pilot = local_payos_pilot(request)
        if pilot and current["role"] != "admin":
            verified = db.one(
                "SELECT 1 FROM customer_profiles p JOIN email_verifications v "
                "ON v.user_id=p.user_id AND v.email=p.email "
                "WHERE p.user_id=? AND v.verified_at IS NOT NULL", (current["id"],),
            )
            if not verified:
                raise HTTPException(409, "Cần email đã xác minh để nhận hướng dẫn Pro. "
                                    "Hãy đăng nhập bằng Google trước khi thanh toán.")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute(
                "SELECT id,status,amount_vnd,checkout_url,payment_order_code FROM orders WHERE user_id=? "
                "AND status IN ('requested','transfer_reported','initiating') "
                "ORDER BY created_at DESC LIMIT 1",
                (current["id"],),
            ).fetchone()
            if pending:
                if pending["amount_vnd"] != PRO_PRICE_VND:
                    raise HTTPException(409, "Đơn đang chờ dùng giá cũ. Đừng thanh toán link cũ; "
                                        f"nhờ Admin từ chối đơn đó để tạo đơn {PRO_PRICE_VND:,}đ mới.".replace(",", "."))
                if pending["status"] == "initiating":
                    raise HTTPException(409, "Đang tạo link payOS. Thử lại sau ít phút.")
                if pilot and pending["checkout_url"]:
                    return {"id": pending["id"], "status": pending["status"],
                            "amount_vnd": pending["amount_vnd"],
                            "checkout_url": pending["checkout_url"],
                            "payment_order_code": pending["payment_order_code"],
                            "message": "Link payOS của đơn đang chờ đã sẵn sàng."}
                if pilot and pending["payment_order_code"]:
                    raise HTTPException(409, "Mã payOS của đơn này chưa tạo xong. "
                                        "Không thử thanh toán lại; Admin sẽ kiểm tra và gắn link an toàn.")
                if not pilot or pending["status"] == "transfer_reported":
                    raise HTTPException(409, "Bạn đã có một yêu cầu Pro đang chờ xử lý.")
                ident = pending["id"]
            else:
                ident = uuid.uuid4().hex
                conn.execute(
                    "INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at) "
                    "VALUES(?,?,'pro_local',?,'requested',?)",
                    (ident, current["id"], PRO_PRICE_VND, now()),
                )
            code = None
            if pilot:
                recent = conn.execute(
                    "SELECT count(*) FROM orders WHERE user_id=? AND payment_order_code IS NOT NULL "
                    "AND created_at>=?", (current["id"],
                        (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()),
                ).fetchone()[0]
                if recent >= 5:
                    raise HTTPException(429, "Đã tạo quá nhiều link payOS. Thử lại sau một giờ.")
                for _ in range(5):
                    code = secrets.randbelow(1_800_000_000) + 100_000_000
                    if not conn.execute("SELECT 1 FROM orders WHERE payment_order_code=?", (code,)).fetchone():
                        break
                else:
                    raise HTTPException(503, "Không tạo được mã thanh toán. Thử lại sau.")
                conn.execute(
                    "UPDATE orders SET status='initiating',payment_order_code=? "
                    "WHERE id=? AND status='requested'", (code, ident),
                )
        if pilot:
            try:
                link = payment_gateway.create_checkout(
                    code, PRO_PRICE_VND, "http://localhost:8770", local_pilot=True,
                )
                with db.connect() as conn:
                    conn.execute(
                        "UPDATE orders SET status='requested',checkout_url=?,payment_link_id=? "
                        "WHERE id=? AND status='initiating'",
                        (link["checkout_url"], link["payment_link_id"], ident),
                    )
            except Exception as exc:
                db.execute("UPDATE orders SET status='requested' "
                           "WHERE id=? AND status='initiating'", (ident,))
                raise HTTPException(502, "Không nhận được mã QR payOS. Chưa có khoản tiền nào được LH25 xác nhận; "
                                    "không thử lại để tránh tạo hai link. Admin sẽ kiểm tra và gắn link cho đơn.") from exc
            db.audit(current["id"], "request_pro_payos_pilot", ident)
            return {"id": ident, "status": "requested", "amount_vnd": PRO_PRICE_VND,
                    "checkout_url": link["checkout_url"], "payment_order_code": code,
                    "message": "Link payOS đã sẵn sàng. Pro chỉ mở sau khi Admin duyệt giao dịch."}
        db.audit(current["id"], "request_pro", ident)
        ready = bool(settings.manual_bank_name and settings.manual_bank_account
                     and settings.manual_bank_recipient)
        return {"id": ident, "status": "requested", "amount_vnd": PRO_PRICE_VND,
                "message": ("Đã nhận yêu cầu. Xem Gói của tôi để chuyển khoản đúng nội dung."
                            if ready else "Đã nhận yêu cầu. Admin sẽ gắn link payOS riêng cho đơn; "
                            "vui lòng chờ link hiển thị trong Gói của tôi trước khi thanh toán.")}

    @app.post("/api/orders/pro-local/checkout", status_code=201)
    def checkout_pro(current=Depends(operator)):
        if not settings.payment_enabled:
            raise HTTPException(503, "Thanh toán tự động chưa được bật; không có giao dịch nào được tạo.")
        require_recipient(current)
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            previous = conn.execute(
                "SELECT id,checkout_url FROM orders WHERE user_id=? AND status='payment_pending' "
                "ORDER BY created_at DESC LIMIT 1", (current["id"],),
            ).fetchone()
            if previous:
                return {"id": previous["id"], "checkout_url": previous["checkout_url"],
                        "status": "payment_pending"}
            active = conn.execute(
                "SELECT 1 FROM orders WHERE user_id=? AND status='initiating' LIMIT 1",
                (current["id"],),
            ).fetchone()
            if active:
                raise HTTPException(409, "Đang tạo liên kết thanh toán. Thử lại sau.")
            recent = conn.execute(
                "SELECT count(*) FROM orders WHERE user_id=? AND payment_order_code IS NOT NULL "
                "AND created_at>=?", (current["id"],
                    (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()),
            ).fetchone()[0]
            if recent >= 5:
                raise HTTPException(429, "Đã tạo quá nhiều liên kết thanh toán. Thử lại sau một giờ.")
            ident = uuid.uuid4().hex
            for _ in range(5):
                code = secrets.randbelow(1_800_000_000) + 100_000_000
                if not conn.execute("SELECT 1 FROM orders WHERE payment_order_code=?", (code,)).fetchone():
                    break
            else:
                raise HTTPException(503, "Không tạo được mã đơn hàng. Thử lại sau.")
            conn.execute(
                "INSERT INTO orders(id,user_id,plan,amount_vnd,status,created_at,payment_order_code) "
                "VALUES(?,?,'pro_local',?,'initiating',?,?)",
                (ident, current["id"], PRO_PRICE_VND, now(), code),
            )
        try:
            link = payment_gateway.create_checkout(code, PRO_PRICE_VND, settings.public_base_url)
            with db.connect() as conn:
                conn.execute(
                    "UPDATE orders SET status='payment_pending',checkout_url=?,payment_link_id=? "
                    "WHERE id=? AND status='initiating'",
                    (link["checkout_url"], link["payment_link_id"], ident),
                )
        except Exception as exc:
            db.execute("UPDATE orders SET status='checkout_failed' WHERE id=? AND status='initiating'",
                       (ident,))
            raise HTTPException(502, "Không tạo được liên kết thanh toán. Chưa có khoản tiền nào được xác nhận.") from exc
        db.audit(current["id"], "checkout_pro", ident)
        return {"id": ident, "checkout_url": link["checkout_url"], "status": "payment_pending"}

    @app.post("/api/payments/payos/webhook")
    async def payos_webhook(request: Request):
        if not settings.payment_enabled and not payment_gateway.available:
            raise HTTPException(503, "Thanh toán tự động chưa được bật.")
        raw = await request.body()
        if len(raw) > 16_384:
            raise HTTPException(413, "Webhook quá lớn.")
        try:
            payload = json.loads(raw)
        except (ValueError, UnicodeDecodeError) as exc:
            raise HTTPException(400, "Webhook không hợp lệ.") from exc
        if not payment_gateway.verify_webhook(payload):
            if not settings.payment_enabled:
                raise HTTPException(503, "Thanh toán tự động chưa được bật.")
            raise HTTPException(400, "Chữ ký webhook không hợp lệ.")
        if not settings.payment_enabled:
            # payOS can validate the callback before checkout is enabled.
            # Do not acknowledge a real pending payment while paused: payOS
            # must retry it when processing is resumed.
            known = db.one("SELECT status FROM orders WHERE payment_order_code=?",
                           (payload["data"].get("orderCode"),))
            if known and known["status"] != "activated":
                raise HTTPException(503, "Xử lý thanh toán đang tạm dừng; vui lòng gửi lại webhook.")
            return {"ok": True, "activated": False, "verification_only": True}
        data = payload["data"]
        if not (payload.get("success") is True and payload.get("code") == "00"
                and data.get("code") == "00"):
            return {"ok": True, "activated": False}
        code = data.get("orderCode")
        if not isinstance(code, int) or isinstance(code, bool):
            raise HTTPException(400, "Mã đơn hàng không hợp lệ.")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM orders WHERE payment_order_code=?", (code,)).fetchone()
            if not order:
                return {"ok": True, "activated": False}
            if order["status"] == "activated":
                return {"ok": True, "activated": False}
            if order["status"] != "payment_pending":
                raise HTTPException(409, "Đơn hàng chưa sẵn sàng nhận webhook.")
            reference = str(data.get("reference", ""))
            if (data.get("amount") != order["amount_vnd"] or data.get("currency") != "VND"
                    or data.get("paymentLinkId") != order["payment_link_id"]
                    or len(reference) < 4):
                raise HTTPException(409, "Thông tin thanh toán không khớp đơn hàng.")
            previous = conn.execute(
                "SELECT plan,expires_at FROM subscriptions WHERE user_id=?", (order["user_id"],)
            ).fetchone()
            expires = pro_expiry(previous)
            try:
                conn.execute(
                    "UPDATE orders SET status='activated',resolved_at=?,paid_at=?,payment_reference=? "
                    "WHERE id=? AND status='payment_pending'",
                    (now(), now(), reference, order["id"]),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Giao dịch đã được ghi nhận cho đơn khác.") from exc
            conn.execute(
                "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
                "VALUES(?,'pro_local',?,'payos_webhook',?) "
                "ON CONFLICT(user_id) DO UPDATE SET plan='pro_local',expires_at=excluded.expires_at,"
                "source=excluded.source,updated_at=excluded.updated_at",
                (order["user_id"], expires, now()),
            )
            enqueue_receipts(conn, order["id"])
        db.audit(order["user_id"], "payos_pro_activated", order["id"])
        receipts.wake.set()
        return {"ok": True, "activated": True}

    @app.get("/api/me/orders")
    def customer_orders(current=Depends(user)):
        return db.all(
            "SELECT id,plan,amount_vnd,status,created_at,paid_at,resolved_at,checkout_url "
            "FROM orders WHERE user_id=? ORDER BY created_at DESC LIMIT 100",
            (current["id"],),
        )

    @app.post("/api/me/orders/{ident}/report-transfer")
    def report_manual_transfer(ident: str, current=Depends(operator)):
        if settings.payment_enabled:
            raise HTTPException(409, "Thanh toán tự động đang bật.")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT status,checkout_url FROM orders WHERE id=? AND user_id=?",
                (ident, current["id"]),
            ).fetchone()
            if not order or order["status"] != "requested":
                raise HTTPException(404, "Không tìm thấy đơn đang chờ của bạn.")
            bank_ready = bool(settings.manual_bank_name and settings.manual_bank_account
                              and settings.manual_bank_recipient)
            if not order["checkout_url"] and not bank_ready:
                raise HTTPException(409, "Chưa có link payOS hoặc hướng dẫn chuyển khoản cho đơn này.")
            changed = conn.execute(
                "UPDATE orders SET status='transfer_reported' "
                "WHERE id=? AND user_id=? AND status='requested'",
                (ident, current["id"]),
            ).rowcount
            if not changed:
                raise HTTPException(404, "Không tìm thấy đơn đang chờ của bạn.")
        db.audit(current["id"], "report_manual_transfer", ident)
        return {"id": ident, "status": "transfer_reported",
                "message": "Đã báo chuyển khoản. Gói Pro vẫn chưa mở; LH25 sẽ đối chiếu sao kê."}

    @app.get("/api/admin/billing-notifications")
    def billing_notifications(current=Depends(admin)):
        return db.all(
            "SELECT id,order_id,channel,status,attempts,delivered_at,last_error "
            "FROM billing_notifications ORDER BY id DESC LIMIT 100"
        )

    @app.get("/api/admin/release-readiness")
    def release_readiness(current=Depends(admin)):
        from .release import release_report
        return release_report(settings, payment_gateway.available, email_sender.available,
                              worker_alive=bool(worker.thread and worker.thread.is_alive()))

    @app.post("/api/admin/orders/{ident}/resend-guide", status_code=202)
    def resend_guide(ident: str, current=Depends(admin)):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT status FROM orders WHERE id=?", (ident,)).fetchone()
            if not order:
                raise HTTPException(404, "Không tìm thấy đơn hàng.")
            if order["status"] != "activated":
                raise HTTPException(409, "Chỉ gửi hướng dẫn cho đơn đã mở Pro.")
            previous = conn.execute("SELECT status,next_attempt FROM billing_notifications WHERE order_id=? AND channel='email'", (ident,)).fetchone()
            if previous and (previous["status"] in {"pending", "processing"} or previous["next_attempt"] > time.time()):
                raise HTTPException(429, "Email đang chờ gửi hoặc vừa gửi. Hãy thử lại sau.")
            conn.execute("INSERT INTO billing_notifications(order_id,channel,status) VALUES(?,'email','pending') "
                         "ON CONFLICT(order_id,channel) DO UPDATE SET status='pending',attempts=0,next_attempt=0,delivered_at=NULL,last_error=''", (ident,))
        receipts.wake.set()
        db.audit(current["id"], "resend_pro_guide", ident)
        return {"queued": True, "note": "Đã xếp hàng; xem trạng thái gửi, không đồng nghĩa email đã đến."}

    @app.get("/api/admin/orders")
    def admin_orders(current=Depends(admin)):
        return db.all(
            "SELECT o.id,o.user_id,o.plan,o.amount_vnd,o.status,o.created_at,"
            "o.resolved_at,o.payment_reference,o.payment_order_code,o.payment_link_id,o.checkout_url,"
            "o.paid_at,u.username,p.display_name,p.email,p.phone "
            "FROM orders o JOIN users u ON u.id=o.user_id "
            "LEFT JOIN customer_profiles p ON p.user_id=o.user_id "
            "ORDER BY o.created_at DESC LIMIT 100"
        )

    @app.post("/api/admin/orders/{ident}/manual-payos-link")
    def attach_manual_payos_link(ident: str, payload: ManualPaymentLink,
                                 current=Depends(admin)):
        if settings.payment_enabled:
            raise HTTPException(409, "Đang dùng thanh toán payOS tự động.")
        parsed = urlparse(payload.url)
        if (parsed.scheme != "https" or parsed.netloc != "pay.payos.vn"
                or not re.fullmatch(r"/web/[A-Za-z0-9_-]{4,128}/?", parsed.path)
                or parsed.params or parsed.query or parsed.fragment):
            raise HTTPException(422, "Chỉ nhận link thanh toán payOS dạng https://pay.payos.vn/web/…")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT status,checkout_url FROM orders WHERE id=?", (ident,)).fetchone()
            if not order:
                raise HTTPException(404, "Không tìm thấy yêu cầu Pro.")
            if order["status"] not in {"requested", "transfer_reported"} or order["checkout_url"]:
                raise HTTPException(409, "Đơn đã xử lý hoặc đã có link payOS; không thể ghi đè.")
            if conn.execute("SELECT 1 FROM orders WHERE checkout_url=?", (payload.url,)).fetchone():
                raise HTTPException(409, "Link payOS đã được dùng cho đơn khác.")
            conn.execute("UPDATE orders SET checkout_url=? WHERE id=?", (payload.url, ident))
        db.audit(current["id"], "attach_manual_payos_link", ident)
        return {"id": ident, "checkout_url": payload.url, "status": order["status"]}

    @app.post("/api/admin/orders/{ident}/activate")
    def activate_order(ident: str, payload: PaymentConfirmation, current=Depends(admin)):
        if settings.payment_enabled:
            raise HTTPException(403, "Khi bật payOS, Pro chỉ mở bằng webhook đã xác minh.")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute("SELECT * FROM orders WHERE id=?", (ident,)).fetchone()
            if not order:
                raise HTTPException(404, "Không tìm thấy yêu cầu Pro.")
            if order["status"] not in {"requested", "transfer_reported"}:
                raise HTTPException(409, "Yêu cầu này đã được xử lý.")
            previous = conn.execute(
                "SELECT plan,expires_at FROM subscriptions WHERE user_id=?", (order["user_id"],)
            ).fetchone()
            try:
                conn.execute(
                    "UPDATE orders SET status='activated',resolved_at=?,paid_at=?,payment_reference=?,"
                    "resolved_by=? WHERE id=?",
                    (now(), now(), payload.payment_reference, current["id"], ident),
                )
            except sqlite3.IntegrityError as exc:
                raise HTTPException(409, "Mã giao dịch này đã được dùng cho đơn khác.") from exc
            expires = pro_expiry(previous)
            conn.execute(
                "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
                "VALUES(?,'pro_local',?,'manual_payment',?) "
                "ON CONFLICT(user_id) DO UPDATE SET plan='pro_local',"
                "expires_at=excluded.expires_at,source=excluded.source,updated_at=excluded.updated_at",
                (order["user_id"], expires, now()),
            )
            enqueue_receipts(conn, ident)
        db.audit(current["id"], "activate_pro", ident)
        receipts.wake.set()
        return {"id": ident, "status": "activated", "expires_at": expires}

    @app.post("/api/admin/orders/{ident}/reject")
    def reject_order(ident: str, current=Depends(admin)):
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            changed = conn.execute(
                "UPDATE orders SET status='rejected',resolved_at=?,resolved_by=? "
                "WHERE id=? AND status IN ('requested','transfer_reported')",
                (now(), current["id"], ident),
            ).rowcount
            if not changed:
                raise HTTPException(404, "Không tìm thấy yêu cầu đang chờ.")
        db.audit(current["id"], "reject_pro", ident)
        return {"id": ident, "status": "rejected"}

    @app.get("/api/profile")
    def profile(current=Depends(user)):
        row = db.one("SELECT display_name,email,phone,updated_at FROM customer_profiles "
                     "WHERE user_id=?", (current["id"],))
        return row or {"display_name": "", "email": "", "phone": "", "updated_at": None}

    @app.put("/api/profile")
    def save_profile(payload: CustomerProfile, current=Depends(user)):
        email = payload.email.lower()
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT 1 FROM customer_profiles WHERE lower(email)=? AND user_id!=?",
                            (email, current["id"])).fetchone():
                raise HTTPException(409, "Email đã được sử dụng cho tài khoản khác.")
            old = conn.execute("SELECT email FROM customer_profiles WHERE user_id=?",
                               (current["id"],)).fetchone()
            conn.execute(
                "INSERT INTO customer_profiles(user_id,display_name,email,phone,updated_at) "
                "VALUES(?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                "display_name=excluded.display_name,email=excluded.email,"
                "phone=excluded.phone,updated_at=excluded.updated_at",
                (current["id"], payload.display_name, email, payload.phone, now()),
            )
            if old and old["email"].lower() != email:
                conn.execute("DELETE FROM email_verifications WHERE user_id=?", (current["id"],))
        db.audit(current["id"], "profile_updated", str(current["id"]))
        return profile(current)

    @app.get("/api/telegram/status")
    def telegram_status(current=Depends(user)):
        return telegram_linker.status(current["id"])

    @app.post("/api/telegram/link")
    def telegram_link(current=Depends(user)):
        if not (current["role"] == "admin" and current["username"] == "admin") and not db.one(
            "SELECT user_id FROM customer_profiles WHERE user_id=?", (current["id"],)
        ):
            raise HTTPException(409, "Điền thông tin khách hàng trước khi kết nối Telegram.")
        try:
            result = telegram_linker.begin(current["id"])
        except TelegramUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        db.audit(current["id"], "telegram_link_started", str(current["id"]))
        return result

    @app.post("/api/telegram/check")
    def telegram_check(current=Depends(user)):
        try:
            result = telegram_linker.check(current["id"])
        except TelegramUnavailable as exc:
            raise HTTPException(503, str(exc)) from exc
        if result["linked"]:
            db.audit(current["id"], "telegram_link_verified", str(current["id"]))
        return result

    @app.delete("/api/telegram/link")
    def telegram_disconnect(current=Depends(user)):
        with db.connect() as conn:
            conn.execute("DELETE FROM telegram_pending WHERE user_id=?", (current["id"],))
            conn.execute("DELETE FROM telegram_accounts WHERE user_id=?", (current["id"],))
            conn.execute("UPDATE jobs SET status='cancelled',cancel=1,finished_at=? "
                         "WHERE user_id=? AND status='queued'", (now(), current["id"]))
            conn.execute("UPDATE jobs SET cancel=1 WHERE user_id=? AND status='running'",
                         (current["id"],))
        db.audit(current["id"], "telegram_unlinked", str(current["id"]))
        return {"ok": True}

    @app.get("/api/users")
    def users(current=Depends(admin)):
        return db.all("SELECT u.id,u.username,u.role,p.display_name,p.email,p.phone,"
                      "CASE WHEN t.user_id IS NULL THEN 0 ELSE 1 END telegram_linked,"
                      "CASE WHEN v.verified_at IS NULL OR v.email!=p.email THEN 0 ELSE 1 END email_verified,"
                      "CASE WHEN u.role='admin' THEN 'admin' "
                      "WHEN s.plan='pro_local' AND (s.expires_at IS NULL OR s.expires_at>?) "
                      "THEN 'pro_local' ELSE 'free' END plan,s.expires_at "
                      "FROM users u LEFT JOIN customer_profiles p ON p.user_id=u.id "
                      "LEFT JOIN telegram_accounts t ON t.user_id=u.id "
                      "LEFT JOIN email_verifications v ON v.user_id=u.id "
                      "LEFT JOIN subscriptions s ON s.user_id=u.id ORDER BY u.id", (now(),))

    @app.post("/api/users", status_code=201)
    def create_user(payload: UserCreate, current=Depends(admin)):
        if settings.google_only:
            raise HTTPException(403, "Chế độ Google-only không tạo tài khoản mật khẩu.")
        try:
            with db.connect() as conn:
                cursor = conn.execute(
                    "INSERT INTO users(username,password,role) VALUES(?,?,?)",
                    (payload.username, hash_password(payload.password), payload.role),
                )
                if payload.role == "operator" and not settings.payment_enabled:
                    conn.execute(
                        "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
                        "VALUES(?,'pro_local',NULL,'admin_pilot',?)",
                        (cursor.lastrowid, now()),
                    )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Tên đăng nhập đã tồn tại.")
        db.audit(current["id"], "create_user", payload.username, payload.role)
        return {"username": payload.username, "role": payload.role}

    @app.get("/api/system")
    def system(current=Depends(user)):
        return {
            "models": {name: (settings.models / (name + ".pt")).is_file() for name in MODELS},
            "model_catalog": catalog(settings.models),
            "sources": db.one("SELECT count(*) n FROM sources")["n"],
            "dataset_available": settings.data_root.is_dir(),
            "worker_alive": bool(worker.thread and worker.thread.is_alive()),
            "max_queue": 10,
            "mode": "local-only",
            "dataset": "ShanghaiTech",
            "fire_available": all(
                (settings.models / name).is_file()
                for name in ("fire-smoke-v1.onnx", "fire-model.json")
            ),
            "weapon_available": False,
            "telegram_configured": recipient_for(db, current["id"], notifier).configured,
            "live_available": any((settings.models / f"{name}.pt").is_file() for name in POSE_MODELS),
            "face_available": models_ready(settings),
            "detection_note": "Nhãn anomaly của ShanghaiTech không phải nhãn bounding box người. Pipeline fine-tune dùng nhãn người riêng; xem Huấn luyện AI để biết kết quả.",
        }

    @app.get("/api/stats")
    def stats(current=Depends(user)):
        own = current["role"] != "admin"
        owned_jobs = " WHERE user_id=?" if own else ""
        owned_alerts = " JOIN jobs j ON j.id=alerts.job_id WHERE j.user_id=?" if own else ""
        args = (current["id"],) if own else ()
        return {
            "sources": db.one("SELECT count(*) n FROM sources" if not own else
                              "SELECT count(*) n FROM source_ownership WHERE user_id=?", args)["n"],
            "jobs": db.all("SELECT status,count(*) count FROM jobs" + owned_jobs + " GROUP BY status", args),
            "alerts": db.all("SELECT alerts.status,count(*) count FROM alerts" + owned_alerts +
                             " GROUP BY alerts.status", args),
            "latest": [
                public_job(x)
                for x in db.all(
                    "SELECT j.*,s.name source_name FROM jobs j JOIN sources s ON j.source_id=s.id "
                    + ("WHERE j.user_id=? " if own else "") +
                    "ORDER BY j.created_at DESC,j.id DESC LIMIT 8", args
                )
            ],
        }

    @app.get("/api/training")
    def training(current=Depends(admin)):
        data_path = settings.runtime / "training-data" / "manifest.json"
        counts = {}
        if data_path.is_file():
            for item in json.loads(data_path.read_text(encoding="utf-8"))["items"]:
                key = item["split"] + "/" + item["source"]
                counts[key] = counts.get(key, 0) + 1
        runs = []
        for path in sorted((settings.runtime / "training-runs").glob("person-adapt*")):
            metrics = []
            result = path / "results.csv"
            if result.is_file():
                with result.open(encoding="utf-8") as stream:
                    for row in csv.DictReader(stream):
                        try:
                            metrics.append({k.strip(): float(v) for k, v in row.items()})
                        except (TypeError, ValueError):
                            continue
            runs.append(
                {
                    "name": path.name,
                    "metrics": metrics,
                    "finished": (path / "provenance.json").is_file(),
                }
            )
        report_path = settings.models / "training-report.json"
        report = (
            json.loads(report_path.read_text(encoding="utf-8")) if report_path.is_file() else None
        )
        event_manifest = settings.runtime / "event-data" / "manifest.json"
        events = (
            json.loads(event_manifest.read_text(encoding="utf-8"))
            if event_manifest.is_file()
            else None
        )
        phone_training = None
        phone_dir = settings.runtime / 'phone-training'
        status_path = phone_dir / 'training-status.json'
        if status_path.is_file():
            try:
                phone_training = json.loads(status_path.read_text(encoding='utf-8'))
                phone_report = phone_dir / 'report.json'
                if phone_report.is_file():
                    phone_training = json.loads(phone_report.read_text(encoding='utf-8'))
                phone_training['epochs_completed'] = 0
                progress = settings.runtime / 'training-runs/phone-body-v2/results.csv'
                if progress.is_file():
                    with progress.open(encoding='utf-8') as stream:
                        for row in csv.DictReader(stream):
                            try:
                                float(row['time'])  # Ignore an incomplete CSV row being written.
                                phone_training['epochs_completed'] = int(float(row['epoch']))
                            except (KeyError, ValueError, TypeError):
                                continue
            except json.JSONDecodeError:
                phone_training = {'status': 'updating'}
        return {
            "counts": counts,
            "runs": runs,
            "report": report,
            "candidate_available": (settings.models / "schoolguard-person-v1.pt").is_file(),
            "event_dataset": events,
            "phone_training": phone_training,
        }

    demo_capabilities = {
        "fall": "Nghi té ngã",
        "fire": "Lửa / khói",
        "people": "Người vượt mức",
        "face": "Khuôn mặt",
        "interaction": "Nghi xung đột",
    }
    demo_event_types = {
        "fall": ("suspected_fall",),
        "fire": ("fire", "smoke"),
        "people": ("unexpected_person", "crowding"),
        "interaction": ("vigorous_interaction",),
    }

    @app.get("/api/admin/demo-videos")
    def demo_videos(current=Depends(admin)):
        rows = db.all(
            "SELECT d.source_id,d.capability,d.evidence_job_id,d.rights_note,d.review_note,d.academic_only,"
            "d.reviewed_at,s.name,s.split,s.path FROM demo_videos d "
            "JOIN sources s ON s.id=d.source_id WHERE d.capability!='weapon' "
            "ORDER BY d.capability,d.reviewed_at DESC"
        )
        for row in rows:
            row["available"] = Path(row.pop("path")).is_file()
            row["evidence_image"] = None
            if row["capability"] == "face":
                face = db.one(
                    "SELECT id,image FROM faces WHERE job_id=? ORDER BY video_time,ordinal LIMIT 1",
                    (row["evidence_job_id"],),
                )
                if face and (settings.runtime / "faces" / face["image"]).is_file():
                    row["evidence_image"] = f"/api/faces/{face['id']}/image"
            elif row["capability"] in demo_event_types:
                kinds = demo_event_types[row["capability"]]
                placeholders = ",".join("?" for _ in kinds)
                alert = db.one(
                    "SELECT id,evidence FROM alerts WHERE job_id=? AND status!='false_positive' "
                    f"AND event_type IN ({placeholders}) ORDER BY confidence DESC LIMIT 1",
                    (row["evidence_job_id"], *kinds),
                )
                if alert and (settings.runtime / "jobs" / row["evidence_job_id"] / alert["evidence"]).is_file():
                    row["evidence_image"] = f"/api/alerts/{alert['id']}/evidence"
        return {"capabilities": demo_capabilities, "items": rows, "limit_per_capability": 5}

    @app.get("/api/admin/demo-videos/jobs/{source_id}")
    def demo_jobs(source_id: str, current=Depends(admin)):
        source(source_id, current)
        jobs = db.all(
            "SELECT id,finished_at FROM jobs WHERE source_id=? AND status='completed' "
            "ORDER BY finished_at DESC LIMIT 30", (source_id,)
        )
        for item in jobs:
            item["events"] = db.all(
                "SELECT event_type,count(*) AS count FROM alerts "
                "WHERE job_id=? AND status!='false_positive' GROUP BY event_type", (item["id"],)
            )
            item["faces"] = db.one(
                "SELECT count(*) AS n FROM faces WHERE job_id=?", (item["id"],)
            )["n"]
        return {"items": jobs}

    @app.post("/api/admin/demo-videos", status_code=201)
    def add_demo_video(payload: DemoPick, current=Depends(admin)):
        selected = source(payload.source_id, current)
        if selected["kind"] != "video" or selected["split"] == "live":
            raise HTTPException(422, "Demo phải là một tệp video có thể phát lại.")
        if selected["split"] == "research" and selected["name"].startswith("[research] ") and not payload.academic_only:
            raise HTTPException(422, "Clip nghiên cứu chỉ được gắn nhãn demo học thuật nội bộ.")
        if not payload.review_confirmed:
            raise HTTPException(422, "Cần xác nhận đã xem video gốc và kết quả AI.")
        evidence = db.one(
            "SELECT id FROM jobs WHERE id=? AND source_id=? AND status='completed'",
            (payload.evidence_job_id, payload.source_id),
        )
        if not evidence:
            raise HTTPException(422, "Chọn tác vụ đã hoàn tất của chính video này.")
        if payload.capability == "face":
            has_signal = db.one("SELECT 1 FROM faces WHERE job_id=? LIMIT 1", (evidence["id"],))
        else:
            kinds = demo_event_types[payload.capability]
            placeholders = ",".join("?" for _ in kinds)
            has_signal = db.one(
                "SELECT 1 FROM alerts WHERE job_id=? AND status!='false_positive' "
                f"AND event_type IN ({placeholders}) LIMIT 1", (evidence["id"], *kinds),
            )
        if not has_signal:
            raise HTTPException(422, "Tác vụ chưa có bằng chứng AI phù hợp hoặc đã bị đánh dấu báo sai.")
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT 1 FROM demo_videos WHERE source_id=? AND capability=?",
                (payload.source_id, payload.capability),
            ).fetchone()
            count = conn.execute(
                "SELECT count(*) FROM demo_videos WHERE capability=?", (payload.capability,)
            ).fetchone()[0]
            if not existing and count >= 5:
                raise HTTPException(409, "Đã đủ 5 video demo cho chức năng này.")
            conn.execute(
                "INSERT INTO demo_videos(source_id,capability,evidence_job_id,rights_note,"
                "review_note,reviewed_by,reviewed_at,academic_only) VALUES(?,?,?,?,?,?,?,?) "
                "ON CONFLICT(source_id,capability) DO UPDATE SET "
                "evidence_job_id=excluded.evidence_job_id,rights_note=excluded.rights_note,"
                "review_note=excluded.review_note,reviewed_by=excluded.reviewed_by,"
                "reviewed_at=excluded.reviewed_at,academic_only=excluded.academic_only",
                (payload.source_id, payload.capability, payload.evidence_job_id,
                 payload.rights_note.strip(), payload.review_note.strip(), current["id"], now(),
                 int(payload.academic_only)),
            )
        db.audit(current["id"], "demo_video_starred", payload.source_id, payload.capability)
        return {"starred": True}

    @app.delete("/api/admin/demo-videos/{capability}/{source_id}")
    def remove_demo_video(capability: str, source_id: str, current=Depends(admin)):
        if capability not in demo_capabilities:
            raise HTTPException(404, "Không có chức năng demo này.")
        with db.connect() as conn:
            cur = conn.execute(
                "DELETE FROM demo_videos WHERE capability=? AND source_id=?", (capability, source_id)
            )
            if not cur.rowcount:
                raise HTTPException(404, "Video chưa được đánh dấu demo.")
        db.audit(current["id"], "demo_video_unstarred", source_id, capability)
        return {"starred": False}

    @app.get("/api/sources")
    def sources(
        q: str = "",
        split: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(40, ge=1, le=100),
        current=Depends(user),
    ):
        own = current["role"] != "admin"
        args = ((current["id"],) if own else ()) + (f"%{q}%", split, split)
        ownership = ("JOIN source_ownership o ON o.source_id=s.id " if own else "")
        where = ("WHERE " + ("o.user_id=? AND " if own else "") +
                 "s.split!='live' AND s.name LIKE ? AND (?='' OR s.split=?)")
        rows = db.all(
            "SELECT s.id,s.name,s.kind,s.split FROM sources s " + ownership
            + where
            + " ORDER BY s.split,s.name,s.id LIMIT ? OFFSET ?",
            (*args, limit, offset),
        )
        return {
            "items": rows,
            "total": db.one("SELECT count(*) n FROM sources s " + ownership + where, args)["n"],
        }

    @app.get("/api/sources/{ident}")
    def source_detail(ident: str, current=Depends(user)):
        row = source(ident, current)
        try:
            info = metadata(row)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {k: v for k, v in row.items() if k != "path"} | info

    @app.get("/api/sources/{ident}/thumbnail")
    def thumbnail(ident: str, current=Depends(user)):
        row = source(ident, current)
        try:
            with Reader(row["path"], row["kind"]) as reader:
                return Response(jpeg(reader.read()), media_type="image/jpeg")
        except ValueError as exc:
            raise HTTPException(422, str(exc))

    @app.post("/api/sources/upload", status_code=201)
    def upload(file: UploadFile, current=Depends(operator)):
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".avi", ".mp4", ".mov", ".mkv"}:
            raise HTTPException(422, "Chọn video AVI, MP4, MOV hoặc MKV.")
        policy = entitlement(db, current)
        max_bytes = min(settings.max_upload_bytes, policy["upload_bytes"] or settings.max_upload_bytes)
        ident = uuid.uuid4().hex
        folder = settings.runtime / "uploads"
        folder.mkdir(exist_ok=True)
        path = folder / (ident + suffix)
        total = 0
        try:
            with path.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise HTTPException(413, "Video vượt giới hạn dung lượng của gói hiện tại.")
                    target.write(chunk)
            with Reader(path):
                pass
            if policy["video_seconds"] is not None and metadata({"path": str(path), "kind": "video"})["duration"] > policy["video_seconds"]:
                raise HTTPException(422, "Video vượt thời lượng của gói hiện tại.")
            name = Path((file.filename or "video").replace("\\", "/")).name[:150]
            with db.connect() as conn:
                conn.execute(
                    "INSERT INTO sources VALUES(?,?,?,?,?)",
                    (ident, name, str(path.resolve()), "video", "uploaded"),
                )
                conn.execute(
                    "INSERT INTO source_ownership(source_id,user_id) VALUES(?,?)",
                    (ident, current["id"]),
                )
            db.audit(current["id"], "upload", ident, name)
            return {"id": ident, "name": name}
        except BaseException as exc:
            path.unlink(missing_ok=True)
            if isinstance(exc, ValueError):
                raise HTTPException(422, str(exc))
            raise
        finally:
            file.file.close()

    @app.post("/api/jobs", status_code=202)
    def create_job(payload: JobRequest, current=Depends(operator)):
        if payload.detect_weapons:
            raise HTTPException(422, "Phát hiện hung khí đã được gỡ khỏi LH25.")
        require_recipient(current)
        selected = source(payload.source_id, current)
        policy = entitlement(db, current)
        if policy["plan"] == "free" and (payload.recognize_faces or payload.detect_fire
                                         or payload.detect_weapons or payload.detect_interactions
                                         or payload.detect_objects):
            raise HTTPException(403, "Tính năng phân tích mở rộng thuộc gói Pro Local.")
        if policy["plan"] == "free" and (payload.effort in {"high", "extra", "extra_max"}
                                         or requires_pro(payload.model)):
            raise HTTPException(403, "Model hoặc mức Effort này thuộc gói Pro Local.")
        if policy["video_seconds"] is not None and metadata(selected)["duration"] > policy["video_seconds"]:
            raise HTTPException(403, "Video vượt thời lượng của gói hiện tại.")
        if not (settings.models / (payload.model + ".pt")).is_file():
            raise HTTPException(409, "Model chưa được tải. Chạy scripts/download_models.py.")
        if payload.detect_objects and payload.model not in COCO_DETECTION_MODELS and not (settings.models / "yolo11s.pt").is_file():
            raise HTTPException(409, "Thiếu yolo11s.pt. Chạy python scripts/download_models.py.")
        if payload.detect_fire and not all(
            (settings.models / name).is_file() for name in ("fire-smoke-v1.onnx", "fire-model.json")
        ):
            raise HTTPException(
                409, "Chưa có model lửa/khói. Chạy python -m scripts.download_fire_model."
            )
        if payload.recognize_faces and face_factory is None and not models_ready(settings):
            raise HTTPException(409, "Chưa có model khuôn mặt. Chạy python -m scripts.download_face_models.")
        ident = uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            policy = entitlement(db, current)
            if policy["video_limit"] is not None:
                used = conn.execute(
                    "SELECT count(*) FROM jobs WHERE user_id=? AND quota_charged=1 "
                    "AND created_at>=? AND status!='failed'",
                    (current["id"], month_start_utc().isoformat()),
                ).fetchone()[0]
                if used >= policy["video_limit"]:
                    raise HTTPException(429, "Đã dùng hết lượt phân tích video tháng này. Xem mục Gói của tôi.")
            pending = conn.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if pending >= 10:
                raise HTTPException(429, "Hàng đợi đã đầy (10 tác vụ).")
            conn.execute(
                "INSERT INTO jobs(id,source_id,status,created_at,config,user_id,quota_charged) "
                "VALUES(?,?,'queued',?,?,?,?)",
                (ident, payload.source_id, now(), payload.model_dump_json(), current["id"],
                 int(policy["video_limit"] is not None)),
            )
        db.audit(current["id"], "create_job", ident)
        worker.wake.set()
        return job(ident, current)

    @app.post("/api/live/start", status_code=201)
    def start_live(payload: JobRequest, current=Depends(operator)):
        """Start one local webcam session using the same detector/rules as video jobs."""
        if payload.detect_weapons:
            raise HTTPException(422, "Phát hiện hung khí đã được gỡ khỏi LH25.")
        if payload.camera_url:
            try:
                validate_camera_url(payload.camera_url)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
        require_recipient(current)
        if not entitlement(db, current)["webcam"]:
            raise HTTPException(403, "Webcam trực tiếp thuộc gói Pro Local. Mở mục Gói của tôi.")
        daily_limit = entitlement(db, current)["webcam_seconds_per_day"]
        if daily_limit is not None:
            today_used = db.one("SELECT seconds FROM daily_camera_usage WHERE user_id=? AND day=?",
                                (current["id"], usage_day()))
            if today_used and today_used["seconds"] >= daily_limit:
                raise HTTPException(429, "Đã dùng hết 5 giờ webcam hôm nay; lượt được làm mới vào 00:00 giờ Việt Nam.")
        if detector_factory is None and not (settings.models / (payload.model + ".pt")).is_file():
            raise HTTPException(409, "Model chưa được tải. Chạy scripts/download_models.py.")
        if payload.detect_objects and payload.model not in COCO_DETECTION_MODELS and not (settings.models / "yolo11s.pt").is_file():
            raise HTTPException(409, "Thiếu yolo11s.pt. Chạy python scripts/download_models.py.")
        if payload.detect_fire and not all(
            (settings.models / name).is_file()
            for name in ("fire-smoke-v1.onnx", "fire-model.json")
        ):
            raise HTTPException(409, "Chưa có model lửa/khói.")
        if payload.recognize_faces and face_factory is None and not models_ready(settings):
            raise HTTPException(409, "Chưa có model khuôn mặt. Chạy python -m scripts.download_face_models.")
        with live_lock:
            if live_sessions:
                stale = [key for key, session in live_sessions.items()
                         if time.monotonic() - session["last_seen"] > 45]
                for key in stale:
                    old = live_sessions.pop(key)
                    with old["lock"]:
                        if old.get("source"):
                            old["source"].close()
                        cancelled = db.one("SELECT cancel FROM jobs WHERE id=?", (key,))["cancel"]
                        db.execute("UPDATE jobs SET status=?,progress=?,finished_at=? WHERE id=?",
                                   ("cancelled" if cancelled else "completed",
                                    0 if cancelled else 1, now(), key))
                if live_sessions:
                    raise HTTPException(409, "Đã có một phiên camera đang chạy.")
            ident = uuid.uuid4().hex
            config = payload.model_copy(update={"source_id": ident, "max_seconds": 0})
            detector = (detector_factory or PersonDetector)(settings, config)
            body_detector = None
            if config.model in POSE_MODELS and detector_factory is None:
                body_model = ("yolov8n" if config.model.startswith("yolov8") else
                              "yolo26s" if config.model.startswith("yolo26") and (settings.models / "yolo26s.pt").is_file() else "yolo11s")
                body_config = config.model_copy(update={"model": body_model})
                body_detector = PersonDetector(
                    settings, body_config,
                    classes=list(range(80)) if config.detect_objects else [0],
                )
            # Standard COCO detection can find people and objects in one pass.
            combined = config.detect_objects and config.model in COCO_DETECTION_MODELS
            if combined:
                detector.classes = list(range(80))
            fire_detector = (fire_factory or FireDetector)(settings) if config.detect_fire else None
            weapon_detector = None  # Retired feature; never infer on new sessions.
            face_ledger = (FaceLedger(db, settings.runtime, "live", ident,
                                      (face_factory or FaceRecognizer)(settings),
                                      user_id=current["id"])
                           if config.recognize_faces else None)
            object_detector = (PersonDetector(settings, config.model_copy(update={"model": "yolo11s", "image_size": 640}),
                                              classes=list(range(1, 80)))
                               if config.detect_objects and not combined and body_detector is None else None)
            analyzer = LiveAnalyzer(config, detector, fire_detector, face_ledger=face_ledger,
                                    object_detector=object_detector, body_detector=body_detector,
                                    weapon_detector=weapon_detector)
            try:
                network_source = NetworkCamera(camera_credentials(payload.camera_url, payload.camera_username,
                                                                  payload.camera_password)) if payload.camera_url else None
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            if network_source:
                network_source.rotation = config.camera_rotation
                network_source.mirror = config.camera_mirror
            live_sessions[ident] = {"source": network_source, "analyzer": analyzer, "lock": threading.RLock(),
                                    "user_id": current["id"], "last_seen": time.monotonic(),
                                    "last_usage_at": time.monotonic()}
            with db.connect() as conn:
                conn.execute("INSERT INTO sources VALUES(?,?,?,?,?)",
                             (ident, config.camera_name, str(settings.runtime / "live" / ident),
                              "live", "live"))
                conn.execute("INSERT INTO source_ownership(source_id,user_id) VALUES(?,?)",
                             (ident, current["id"]))
                conn.execute(
                    "INSERT INTO jobs(id,source_id,status,created_at,config,user_id) "
                    "VALUES(?,?,'running',?,?,?)",
                    (ident, ident, now(), config.model_dump_json(), current["id"]),
                )
            (settings.runtime / "jobs" / ident).mkdir(parents=True, exist_ok=True)
        db.audit(current["id"], "start_live", ident)
        return {"id": ident, "config": config.model_dump()}

    @app.post("/api/live/{ident}/frame")
    def analyze_live_frame(ident: str, file: UploadFile, current=Depends(operator)):
        require_recipient(current)
        if not entitlement(db, current)["webcam"]:
            raise HTTPException(403, "Gói Pro đã hết hạn; dừng camera và gia hạn để tiếp tục.")
        session = live_sessions.get(ident)
        if not session:
            raise HTTPException(404, "Phiên camera không còn chạy.")
        if current["id"] != session["user_id"] and current["role"] != "admin":
            raise HTTPException(403, "Không phải phiên camera của bạn.")
        if file.content_type != "image/jpeg":
            raise HTTPException(415, "Camera cần gửi JPEG.")
        data = file.file.read(3 * 1024 * 1024 + 1)
        with session["lock"]:
            if ident not in live_sessions:
                raise HTTPException(404, "Phiên camera không còn chạy.")
            daily_limit = entitlement(db, current)["webcam_seconds_per_day"]
            if daily_limit is not None:
                stamp = time.monotonic()
                elapsed = min(max(0, stamp - session["last_usage_at"]), 5)
                used = db.one("SELECT seconds FROM daily_camera_usage WHERE user_id=? AND day=?",
                              (session["user_id"], usage_day()))
                if (used["seconds"] if used else 0) + elapsed >= daily_limit:
                    raise HTTPException(429, "Đã dùng hết 5 giờ webcam hôm nay. Dừng camera và thử lại ngày mai.")
                db.execute("INSERT INTO daily_camera_usage(user_id,day,seconds) VALUES(?,?,?) "
                           "ON CONFLICT(user_id,day) DO UPDATE SET seconds=seconds+excluded.seconds",
                           (session["user_id"], usage_day(), elapsed))
                session["last_usage_at"] = stamp
            try:
                result = session["analyzer"].update(data)
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            session["last_seen"] = time.monotonic()
            frame = result.pop("frame")
            for alert in result["alerts"]:
                alert_id = uuid.uuid4().hex
                evidence_bytes = jpeg(frame)
                evidence_name = alert_id + ".jpg"
                (settings.runtime / "jobs" / ident / evidence_name).write_bytes(evidence_bytes)
                db.execute(
                    "INSERT INTO alerts(id,job_id,created_at,video_time,zone,track_id,confidence,"
                    "bbox,dwell,evidence,event_type,severity,details) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (alert_id, ident, now(), result["time"], alert["zone"],
                     alert.get("track_id") if alert.get("track_id") is not None else -1,
                     alert["confidence"], json.dumps(alert["bbox"]), alert["dwell"],
                     evidence_name, alert.get("event_type", "restricted_zone"),
                     alert.get("severity", "warning"),
                     json.dumps(alert.get("details", {}), ensure_ascii=False)),
                )
                _, delivery_status = recipient_for(db, session["user_id"], notifier).send(
                    alert, evidence_bytes, session["analyzer"].config.camera_name, result["time"]
                )
                db.execute("UPDATE alerts SET telegram_status=? WHERE id=?",
                           (delivery_status, alert_id))
                alert["id"] = alert_id
                alert["telegram_status"] = delivery_status
            db.execute("UPDATE jobs SET frames=?,people=?,events=? WHERE id=?",
                       (session["analyzer"].frames, result["people"],
                        db.one("SELECT count(*) n FROM alerts WHERE job_id=?", (ident,))["n"], ident))
        return result

    def remote_session(ident, current):
        session = live_sessions.get(ident)
        if not session:
            raise HTTPException(404, 'Phiên camera không còn chạy.')
        if current['id'] != session['user_id'] and current['role'] != 'admin':
            raise HTTPException(403, 'Không phải phiên camera của bạn.')
        if not session.get('source'):
            raise HTTPException(422, 'Phiên này không sử dụng camera mạng.')
        require_recipient(current)
        if not entitlement(db, current)['webcam']:
            raise HTTPException(403, 'Gói Pro đã hết hạn; dừng camera và gia hạn để tiếp tục.')
        return session

    @app.get('/api/live/{ident}/preview')
    def remote_camera_preview(ident: str, current=Depends(operator)):
        session = remote_session(ident, current)
        try:
            data = session['source'].jpeg()
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        session['last_seen'] = time.monotonic()
        return Response(data, media_type='image/jpeg', headers={'Cache-Control': 'no-store'})

    @app.patch('/api/live/{ident}/view')
    def remote_camera_view(ident: str, payload: CameraView, current=Depends(operator)):
        session = remote_session(ident, current)
        with session['lock']:
            if ident not in live_sessions:
                raise HTTPException(404, 'Phiên camera không còn chạy.')
            analyzer = session['analyzer']
            if analyzer.config.zones:
                raise HTTPException(409, 'Dừng camera và vẽ lại vùng trước khi đổi hướng hình.')
            session['source'].set_view(payload.rotation, payload.mirror)
            analyzer.config.camera_rotation = payload.rotation
            analyzer.config.camera_mirror = payload.mirror
            analyzer.reset_view()
            session['last_seen'] = time.monotonic()
            db.execute('UPDATE jobs SET config=? WHERE id=?', (analyzer.config.model_dump_json(), ident))
        return payload.model_dump()

    @app.post('/api/live/{ident}/remote-frame')
    def remote_camera_frame(ident: str, current=Depends(operator)):
        session = remote_session(ident, current)
        # Keep orientation changes atomic with frame capture and inference.
        with session['lock']:
            try:
                data = session['source'].jpeg()
            except ValueError as exc:
                raise HTTPException(422, str(exc)) from exc
            from starlette.datastructures import Headers
            file = UploadFile(io.BytesIO(data), filename='camera.jpg',
                              headers=Headers({'content-type': 'image/jpeg'}))
            try:
                result = analyze_live_frame(ident, file, current)
            finally:
                file.file.close()
            result['preview'] = base64.b64encode(data).decode('ascii')
            return result

    @app.post("/api/live/{ident}/stop")
    def stop_live(ident: str, current=Depends(operator)):
        with live_lock:
            session = live_sessions.get(ident)
            if not session:
                raise HTTPException(404, "Phiên camera không còn chạy.")
            if current["id"] != session["user_id"] and current["role"] != "admin":
                raise HTTPException(403, "Không phải phiên camera của bạn.")
            with session["lock"]:
                live_sessions.pop(ident)
                if session.get("source"):
                    session["source"].close()
                cancelled = db.one("SELECT cancel FROM jobs WHERE id=?", (ident,))["cancel"]
                db.execute("UPDATE jobs SET status=?,progress=?,finished_at=? WHERE id=?",
                           ("cancelled" if cancelled else "completed",
                            0 if cancelled else 1, now(), ident))
        db.audit(current["id"], "stop_live", ident)
        return {"ok": True}

    @app.get("/api/jobs")
    def jobs(
        offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), current=Depends(user)
    ):
        own = current["role"] != "admin"
        args = (current["id"],) if own else ()
        return {
            "items": [
                public_job(x)
                for x in db.all(
                    "SELECT j.*,s.name source_name FROM jobs j JOIN sources s ON j.source_id=s.id "
                    + ("WHERE j.user_id=? " if own else "") +
                    "ORDER BY j.created_at DESC,j.id DESC LIMIT ? OFFSET ?",
                    (*args, limit, offset),
                )
            ],
            "total": db.one("SELECT count(*) n FROM jobs" +
                            (" WHERE user_id=?" if own else ""), args)["n"],
        }

    @app.get("/api/jobs/{ident}")
    def get_job(ident: str, current=Depends(user)):
        return job(ident, current)

    @app.get("/api/jobs/{ident}/people")
    def job_people(ident: str, current=Depends(user)):
        job(ident, current)
        path = settings.runtime / "jobs" / ident / "people.json"
        if not path.is_file():
            return {"items": [], "count": 0, "available": False,
                    "count_is_tracks_not_unique_identities": True}
        return {**json.loads(path.read_text(encoding="utf-8")), "available": True}

    @app.get("/api/jobs/{ident}/weapons")
    def job_weapons(ident: str, offset: int = Query(0, ge=0),
                    limit: int = Query(100, ge=1, le=500), current=Depends(user)):
        job(ident, current)
        rows = db.all(
            "SELECT id,video_time,confidence,bbox,details,status,note,telegram_status "
            "FROM alerts WHERE job_id=? AND event_type='weapon' "
            "ORDER BY video_time,id LIMIT ? OFFSET ?", (ident, limit, offset),
        )
        for row in rows:
            row["bbox"] = json.loads(row["bbox"])
            row["details"] = json.loads(row["details"])
        return {"items": rows, "total": db.one(
            "SELECT count(*) n FROM alerts WHERE job_id=? AND event_type='weapon'",
            (ident,),
        )["n"]}

    @app.get("/api/jobs/{ident}/people/{track_id}/image")
    def job_person_image(ident: str, track_id: int, current=Depends(user)):
        job(ident, current)
        if track_id < 0:
            raise HTTPException(404, "Không có ảnh người này.")
        directory = settings.runtime / "jobs" / ident
        manifest = directory / "people.json"
        if not manifest.is_file() or not any(
            row["track_id"] == track_id and row.get("image") == f"person-{track_id}.jpg"
            for row in json.loads(manifest.read_text(encoding="utf-8"))["items"]
        ):
            raise HTTPException(404, "Không có ảnh người này.")
        image = directory / f"person-{track_id}.jpg"
        if not image.is_file():
            raise HTTPException(404, "Ảnh người chưa sẵn sàng.")
        return FileResponse(image, media_type="image/jpeg")

    @app.post("/api/jobs/{ident}/cancel")
    def cancel_job(ident: str, current=Depends(operator)):
        job(ident, current)
        with db.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='cancelled',cancel=1,finished_at=? WHERE id=? AND status='queued'",
                (now(), ident),
            )
            conn.execute("UPDATE jobs SET cancel=1 WHERE id=? AND status='running'", (ident,))
        db.audit(current["id"], "cancel_job", ident)
        return job(ident, current)

    @app.get("/api/jobs/{ident}/files/{name}")
    def artifact(ident: str, name: str, current=Depends(user)):
        row = job(ident, current)
        allowed = {"preview.jpg", "summary.json", "config.json", "detections.jsonl"}
        if row["status"] == "completed":
            allowed.add("result.mp4")
        if name not in allowed:
            raise HTTPException(404, "Không có tệp này.")
        path = settings.runtime / "jobs" / ident / name
        if not path.is_file():
            raise HTTPException(404, "Tệp chưa sẵn sàng.")
        if name == "preview.jpg":
            with worker.preview_lock:
                content = path.read_bytes()
            return Response(content, media_type="image/jpeg")
        return FileResponse(path)

    @app.get("/api/faces/days")
    def face_days(limit: int = Query(31, ge=1, le=366), current=Depends(user)):
        own = current["role"] != "admin"
        rows = db.all(
            "SELECT f.day,count(*) count FROM faces f JOIN jobs j ON j.id=f.job_id "
            "WHERE f.kind='live' " + ("AND j.user_id=? " if own else "") +
            "GROUP BY f.day ORDER BY f.day DESC LIMIT ?",
            ((current["id"], limit) if own else (limit,)),
        )
        return {"items": rows}

    @app.get("/api/faces")
    def faces(job_id: str = "", day: str = "", offset: int = Query(0, ge=0),
              limit: int = Query(100, ge=1, le=500), current=Depends(user)):
        if bool(job_id) == bool(day):
            raise HTTPException(422, "Chọn một video hoặc một ngày webcam.")
        if job_id:
            job(job_id, current)
            where, args = "WHERE f.kind='video' AND f.job_id=?", (job_id,)
        else:
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(422, "Ngày phải có dạng YYYY-MM-DD.") from exc
            where, args = "WHERE f.kind='live' AND f.day=?", (day,)
        if current["role"] != "admin":
            where += " AND j.user_id=?"
            args += (current["id"],)
        base = " FROM faces f JOIN jobs j ON j.id=f.job_id " + where
        rows = db.all(
            "SELECT f.id,f.kind,f.job_id,f.day,f.ordinal,f.first_seen,f.last_seen,f.video_time,"
            "f.seen_count,f.confidence" + base +
            " ORDER BY f.ordinal LIMIT ? OFFSET ?", (*args, limit, offset)
        )
        return {"items": rows, "total": db.one("SELECT count(*) n" + base, args)["n"]}

    def remove_live_faces(ident="", day="", current=None):
        if day:
            try:
                if date.fromisoformat(day).isoformat() != day:
                    raise ValueError
            except ValueError as exc:
                raise HTTPException(422, "Ngày phải có dạng YYYY-MM-DD.") from exc
        with live_lock, ExitStack() as stack:
            for session in live_sessions.values():
                stack.enter_context(session['lock'])
            field, value = ("f.id", ident) if ident else ("f.day", day)
            owner = "" if current.get("role") == "admin" else " AND j.user_id=?"
            args = (value,) if not owner else (value, current["id"])
            with db.connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                rows = conn.execute(
                    "SELECT f.id,f.image FROM faces f JOIN jobs j ON j.id=f.job_id "
                    f"WHERE f.kind='live' AND {field}=?" + owner, args,
                ).fetchall()
                if ident and not rows:
                    raise HTTPException(404, "Không tìm thấy khuôn mặt webcam.")
                conn.executemany("DELETE FROM faces WHERE id=?", ((row["id"],) for row in rows))
            for row in rows:
                if row['image'] == row['id'] + '.jpg' and all(c in '0123456789abcdef' for c in row['id']):
                    (settings.runtime / 'faces' / row['image']).unlink(missing_ok=True)
            for session in live_sessions.values():
                analyzer = session['analyzer']
                if analyzer.face_ledger:
                    analyzer.face_ledger.scope = None
                    analyzer.face_ledger.refresh_scope()
                    analyzer.face_state = {'visible': [], 'total': len(analyzer.face_ledger.records),
                                           'day': analyzer.face_ledger.day}
                    analyzer.last_face = -10.0
        db.audit(current['id'], 'delete_live_faces', ident or day)
        return {'deleted': len(rows)}

    @app.delete('/api/faces')
    def delete_face_day(day: str, current=Depends(operator)):
        return remove_live_faces(day=day, current=current)

    @app.delete('/api/faces/{ident}')
    def delete_face(ident: str, current=Depends(operator)):
        return remove_live_faces(ident=ident, current=current)

    @app.get("/api/faces/{ident}/image")
    def face_image(ident: str, current=Depends(user)):
        row = db.one("SELECT f.image,j.user_id FROM faces f JOIN jobs j ON j.id=f.job_id "
                     "WHERE f.id=?", (ident,))
        if row and current["role"] != "admin" and row["user_id"] != current["id"]:
            raise HTTPException(404, "Không có ảnh khuôn mặt.")
        if not row or row["image"] != ident + ".jpg":
            raise HTTPException(404, "Không có ảnh khuôn mặt.")
        path = settings.runtime / "faces" / row["image"]
        if not path.is_file():
            raise HTTPException(404, "Ảnh khuôn mặt không còn trên máy.")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/alerts")
    def alerts(
        job_id: str = "",
        status: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        current=Depends(user),
    ):
        if job_id:
            job(job_id, current)
        own = current["role"] != "admin"
        where = ("WHERE (?='' OR a.job_id=?) AND (?='' OR a.status=?)" +
                 (" AND j.user_id=?" if own else ""))
        args = (job_id, job_id, status, status) + ((current["id"],) if own else ())
        from_clause = (" FROM alerts a JOIN jobs j ON j.id=a.job_id "
                       "JOIN sources s ON s.id=j.source_id ")
        rows = db.all(
            "SELECT a.*,s.name source_name,j.config" + from_clause
            + where
            + " ORDER BY a.created_at DESC,a.id DESC LIMIT ? OFFSET ?",
            (*args, limit, offset),
        )
        for row in rows:
            row["bbox"] = json.loads(row["bbox"])
            row["details"] = json.loads(row["details"])
            row["camera_name"] = json.loads(row.pop("config"))["camera_name"]
        return {
            "items": rows,
            "total": db.one("SELECT count(*) n" + from_clause + where, args)["n"],
        }

    @app.patch("/api/alerts/{ident}")
    def review_alert(ident: str, payload: AlertUpdate, current=Depends(operator)):
        with db.connect() as conn:
            row = conn.execute("SELECT a.id,j.user_id FROM alerts a "
                               "JOIN jobs j ON j.id=a.job_id WHERE a.id=?", (ident,)).fetchone()
            if not row or (current["role"] != "admin" and row["user_id"] != current["id"]):
                raise HTTPException(404, "Không có cảnh báo.")
            conn.execute(
                "UPDATE alerts SET status=?,note=?,reviewed_by=? WHERE id=?",
                (payload.status, payload.note, current["id"], ident),
            )
            conn.execute(
                "INSERT INTO audit(at,user_id,action,target,detail) VALUES(?,?,?,?,?)",
                (now(), current["id"], "review_alert", ident, payload.model_dump_json()),
            )
        return {"ok": True}

    @app.get("/api/alerts/{ident}/evidence")
    def evidence(ident: str, current=Depends(user)):
        row = db.one("SELECT a.job_id,a.evidence,j.user_id FROM alerts a "
                     "JOIN jobs j ON j.id=a.job_id WHERE a.id=?", (ident,))
        if not row or (current["role"] != "admin" and row["user_id"] != current["id"]):
            raise HTTPException(404, "Không có cảnh báo.")
        path = settings.runtime / "jobs" / row["job_id"] / row["evidence"]
        if not path.is_file():
            raise HTTPException(404, "Không tìm thấy ảnh bằng chứng.")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/api/alerts/{ident}/object")
    def weapon_evidence_crop(ident: str, current=Depends(user)):
        import cv2

        row = db.one("SELECT a.job_id,a.evidence,a.bbox,j.user_id FROM alerts a "
                     "JOIN jobs j ON j.id=a.job_id WHERE a.id=? AND a.event_type='weapon'",
                     (ident,))
        if not row or (current["role"] != "admin" and row["user_id"] != current["id"]):
            raise HTTPException(404, "Không có bằng chứng hung khí.")
        directory = (settings.runtime / "jobs" / row["job_id"]).resolve()
        path = (directory / row["evidence"]).resolve()
        if not path.is_relative_to(directory) or not path.is_file():
            raise HTTPException(404, "Không tìm thấy ảnh bằng chứng.")
        image = cv2.imread(str(path))
        if image is None:
            raise HTTPException(404, "Ảnh bằng chứng không đọc được.")
        box = json.loads(row["bbox"])
        if not isinstance(box, list) or len(box) != 4 or not all(
                isinstance(v, (float, int)) and 0 <= v <= 1 for v in box):
            raise HTTPException(404, "Không có vùng vật thể hợp lệ.")
        height, width = image.shape[:2]
        x1, y1, x2, y2 = box
        padding = max(.04, (x2 - x1) * .5, (y2 - y1) * .5)
        left, top = max(0, int((x1 - padding) * width)), max(0, int((y1 - padding) * height))
        right, bottom = min(width, int((x2 + padding) * width)), min(height, int((y2 + padding) * height))
        if right <= left or bottom <= top:
            raise HTTPException(404, "Không có vùng vật thể hợp lệ.")
        ok, encoded = cv2.imencode(".jpg", image[top:bottom, left:right])
        if not ok:
            raise HTTPException(500, "Không tạo được ảnh vật thể.")
        return Response(encoded.tobytes(), media_type="image/jpeg",
                        headers={"Cache-Control": "no-store"})

    @app.post("/api/alerts/{ident}/telegram")
    def retry_telegram(ident: str, current=Depends(operator)):
        """Manually resend an unsent alert; never resend a confirmed delivery."""
        with telegram_retry_lock:
            row = db.one(
                "SELECT a.*,j.config,j.status job_status,j.user_id FROM alerts a "
                "JOIN jobs j ON j.id=a.job_id WHERE a.id=?", (ident,)
            )
            if not row or (current["role"] != "admin" and row["user_id"] != current["id"]):
                raise HTTPException(404, "Không có cảnh báo.")
            destination = recipient_for(db, row["user_id"], notifier)
            if not destination.configured:
                raise HTTPException(409, "Chưa kết nối Telegram cho tài khoản tạo cảnh báo.")
            if row["telegram_status"] == "delivered":
                raise HTTPException(409, "Cảnh báo này đã gửi Telegram.")
            retryable = {"telegram_not_configured", "telegram_delivery_failed", "telegram_rejected"}
            if row["telegram_status"] not in retryable and not (
                row["telegram_status"] == "pending"
                and row["job_status"] in {"completed", "failed", "cancelled"}
            ):
                raise HTTPException(409, "Cảnh báo đang được gửi hoặc chưa sẵn sàng gửi lại.")
            directory = (settings.runtime / "jobs" / row["job_id"]).resolve()
            path = (directory / row["evidence"]).resolve()
            if not path.is_relative_to(directory) or not path.is_file():
                raise HTTPException(404, "Không tìm thấy ảnh bằng chứng.")
            alert = {"zone": row["zone"], "event_type": row["event_type"],
                     "details": json.loads(row["details"])}
            config = json.loads(row["config"])
            delivered, status = destination.send(
                alert, path.read_bytes(), config["camera_name"], row["video_time"]
            )
            db.execute("UPDATE alerts SET telegram_status=? WHERE id=?", (status, ident))
            db.audit(current["id"], "retry_telegram", ident, status)
            return {"delivered": delivered, "telegram_status": status}

    @app.get("/api/export/alerts.csv")
    def export(current=Depends(user)):
        own = current["role"] != "admin"
        rows = db.all(
            "SELECT a.id,a.job_id,a.created_at,a.video_time,a.zone,a.track_id,a.confidence,"
            "a.dwell,a.status,a.note,a.event_type,a.severity,a.details "
            "FROM alerts a JOIN jobs j ON j.id=a.job_id " +
            ("WHERE j.user_id=? " if own else "") + "ORDER BY a.created_at,a.id",
            (current["id"],) if own else (),
        )
        stream = io.StringIO()
        fields = [
            "id",
            "job_id",
            "created_at",
            "video_time",
            "zone",
            "track_id",
            "confidence",
            "dwell",
            "status",
            "note",
            "event_type",
            "severity",
            "details",
        ]
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    k: (
                        "'" + v
                        if isinstance(v, str) and v.startswith(("=", "+", "-", "@", "\t", "\r"))
                        else v
                    )
                    for k, v in row.items()
                }
            )
        return Response(
            "\ufeff" + stream.getvalue(),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="schoolguard-alerts.csv"'},
        )

    @app.get("/api/audit")
    def audit(current=Depends(admin)):
        return db.all(
            "SELECT a.*,u.username FROM audit a LEFT JOIN users u ON u.id=a.user_id ORDER BY a.id DESC LIMIT 100"
        )

    static = Path(__file__).with_name("static")
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    def index():
        return FileResponse(static / "index.html")

    @app.get("/store")
    def store():
        return FileResponse(static / "store.html")

    @app.get("/terms")
    def terms_page():
        return FileResponse(static / "terms.html")

    @app.get("/privacy")
    def privacy_page():
        return FileResponse(static / "privacy.html")

    @app.get("/admin")
    def admin_page(request: Request):
        try:
            admin(user(request))
        except HTTPException as exc:
            if exc.status_code == 401:
                return RedirectResponse("/admin/login", status_code=303)
            raise
        return FileResponse(static / "admin.html", headers={"Cache-Control": "no-store"})

    @app.get("/admin/login")
    def admin_login_page():
        return FileResponse(static / "admin-login.html", headers={"Cache-Control": "no-store"})

    @app.get("/verify-email")
    def verify_email_page():
        return FileResponse(static / "verify-email.html")

    @app.get("/payment-return")
    @app.get("/payment-cancel")
    def payment_return_page():
        # Browser redirects are not proof of payment; only a verified webhook grants Pro.
        return FileResponse(static / "payment-return.html")

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    return app
