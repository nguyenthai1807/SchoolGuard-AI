import hashlib
import json
import logging
import mimetypes
import os
import secrets
import shutil
import smtplib
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from pathlib import Path
from threading import Lock
from time import monotonic

import cv2
import requests
from fastapi import (
    Depends,
    FastAPI,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    create_engine,
    inspect,
    or_,
)
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from starlette.background import BackgroundTask
from starlette.concurrency import run_in_threadpool

from home_video_analysis import (
    analyze_person_video,
    can_use_person_worker,
    validate_video_duration,
)
from video_analysis import (
    analyze_video,
    annotate_live_event_jpeg,
    detect_live_frame_jpeg,
    release_live_stream,
)


def _load_local_env():
    env_file = Path(__file__).with_name(".env")
    if not env_file.is_file():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


_load_local_env()


BASE_DIR = Path(__file__).resolve().parent
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{BASE_DIR / 'schoolguard.db'}")
engine_options = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

configured_upload_dir = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR = configured_upload_dir if configured_upload_dir.is_absolute() else BASE_DIR / configured_upload_dir
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
VIDEO_RUNS_DIR = UPLOAD_DIR / "analysis-runs"
VIDEO_RUNS_DIR.mkdir(parents=True, exist_ok=True)
TEST_VIDEO_DIR = BASE_DIR / "videos"
TEST_VIDEO_NAMES = ("Video1.mp4", "Video2.mp4", "Video3.mp4")
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
TOKEN_TTL = timedelta(hours=8)
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_ATTEMPTS = 5
MAX_VIDEO_RESULTS = max(1, int(os.getenv("MAX_VIDEO_RESULTS", "10")))
VIDEO_RESULT_TTL = timedelta(hours=float(os.getenv("VIDEO_RESULT_TTL_HOURS", "24")))
EVENT_STATUSES = (
    "Chưa xử lý",
    "Đã xác nhận",
    "Đang xử lý",
    "Đã hoàn tất",
    "Cảnh báo sai",
)
active_tokens = {}
token_usernames = {}
video_results = {}
active_video_downloads = set()
login_failures = {}
auth_lock = Lock()
video_analysis_lock = Lock()
live_detection_lock = Lock()
video_results_lock = Lock()
logger = logging.getLogger("schoolguard")

app = FastAPI(
    title="SchoolGuard AI Home Monitor",
    description="Local-first person detection for uploaded videos and a home webcam.",
)
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    script_sources = "'self' 'unsafe-inline'"
    if request.url.path == "/local" and os.getenv("ENABLE_BROWSER_ONLY_MODE", "false").lower() == "true":
        script_sources += " https://cdn.jsdelivr.net"
    response.headers["Content-Security-Policy"] = (
        f"default-src 'self'; script-src {script_sources}; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self' https://cdn.jsdelivr.net; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    response.headers["Permissions-Policy"] = "camera=(self), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


class UserDB(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="admin")


class CameraDB(Base):
    __tablename__ = "cameras"
    id = Column(String, primary_key=True, index=True)
    name = Column(String, nullable=False)
    zone_id = Column(Integer, ForeignKey("zones.id"), nullable=True)
    stream_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="offline")
    zone = relationship("ZoneDB", back_populates="cameras")


class ZoneDB(Base):
    __tablename__ = "zones"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)
    cameras = relationship("CameraDB", back_populates="zone")


class AlertDB(Base):
    __tablename__ = "alerts"
    id = Column(Integer, primary_key=True, index=True)
    camera_id = Column(String, index=True, nullable=False)
    zone_name = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    image_url = Column(String, nullable=False)
    status = Column(String, default="Mới", nullable=False, index=True)


class DetectionEventDB(Base):
    __tablename__ = "detection_events"
    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, nullable=False)
    source_id = Column(String, nullable=False, index=True)
    zone_id = Column(String, nullable=False)
    zone_name = Column(String, nullable=False)
    object_type = Column(String, nullable=False)
    track_id = Column(Integer, nullable=True)
    occurred_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    media_offset_seconds = Column(Float, nullable=True)
    image_path = Column(String, nullable=False)
    status = Column(String, nullable=False, default="Chưa xử lý", index=True)
    note = Column(String, nullable=True)
    activities = relationship(
        "EventActivityDB",
        back_populates="event",
        cascade="all, delete-orphan",
        order_by="EventActivityDB.occurred_at",
    )


class EventActivityDB(Base):
    __tablename__ = "event_activities"
    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(Integer, ForeignKey("detection_events.id"), nullable=False, index=True)
    occurred_at = Column(DateTime, default=datetime.now, nullable=False, index=True)
    actor = Column(String, nullable=False)
    action = Column(String, nullable=False)
    status = Column(String, nullable=False)
    note = Column(String, nullable=True)
    event = relationship("DetectionEventDB", back_populates="activities")


class NotificationSettingsDB(Base):
    __tablename__ = "notification_settings"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, ForeignKey("users.username"), unique=True, nullable=False, index=True)
    email = Column(String, nullable=True)
    phone = Column(String, nullable=True)
    channel = Column(String, nullable=False, default="none")


def serialize_alert(alert: AlertDB):
    timestamp = alert.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=UTC)
    else:
        timestamp = timestamp.astimezone(UTC)
    image_url = f"/api/alerts/{alert.id}/image"
    return {
        "id": alert.id,
        "camera_id": alert.camera_id,
        "zone_name": alert.zone_name,
        "location": alert.zone_name,
        "timestamp": timestamp,
        "image_url": image_url,
        "evidence_image_url": image_url,
        "status": alert.status,
    }


Base.metadata.create_all(bind=engine)


def _migrate_detection_event_columns():
    """Add FE-3 workflow fields to databases created by earlier MVP builds."""
    EventActivityDB.__table__.create(bind=engine, checkfirst=True)
    columns = {column["name"] for column in inspect(engine).get_columns("detection_events")}
    statements = []
    if "status" not in columns:
        statements.append(
            "ALTER TABLE detection_events ADD COLUMN status VARCHAR NOT NULL DEFAULT 'Chưa xử lý'"
        )
    if "note" not in columns:
        statements.append("ALTER TABLE detection_events ADD COLUMN note VARCHAR")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.exec_driver_sql(statement)
    timestamp_column = "d.occurred_at" if "occurred_at" in columns else "CURRENT_TIMESTAMP"
    with engine.begin() as connection:
        connection.exec_driver_sql(
            f"""
            INSERT INTO event_activities (event_id, occurred_at, actor, action, status, note)
            SELECT d.id, {timestamp_column}, 'system', 'Sự kiện trước khi nâng cấp',
                   COALESCE(d.status, 'Chưa xử lý'), NULL
            FROM detection_events AS d
            WHERE NOT EXISTS (
                SELECT 1 FROM event_activities AS a WHERE a.event_id = d.id
            )
            """
        )


_migrate_detection_event_columns()


def _send_event_email(event, image_path, recipient=None):
    recipient = (recipient or os.getenv("ADMIN_EMAIL", "")).strip()
    if not recipient or not os.getenv("SMTP_HOST") or not os.getenv("SMTP_USER") or not os.getenv("SMTP_PASSWORD"):
        return "not_configured"
    message = EmailMessage()
    message["Subject"] = f"SchoolGuard: {event['object_type']} vào {event['zone_name']}"
    message["From"] = os.getenv("SMTP_FROM", os.getenv("SMTP_USER"))
    message["To"] = recipient
    when = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
    offset = f"\nThời điểm trong video: {event['media_offset_seconds']} giây" if event.get("media_offset_seconds") is not None else ""
    message.set_content(f"Phát hiện {event['object_type']} (ID {event.get('track_id') or 'N/A'}) ở {event['zone_name']} lúc {when}.{offset}")
    with open(image_path, "rb") as image_file:
        message.add_attachment(image_file.read(), maintype="image", subtype="jpeg", filename=Path(image_path).name)
    with smtplib.SMTP(os.getenv("SMTP_HOST"), int(os.getenv("SMTP_PORT", "587")), timeout=15) as smtp:
        smtp.starttls()
        smtp.login(os.getenv("SMTP_USER"), os.getenv("SMTP_PASSWORD"))
        smtp.send_message(message)
    return "sent"


def _send_camera_sms(event, recipient=None):
    sid, token = os.getenv("TWILIO_ACCOUNT_SID"), os.getenv("TWILIO_AUTH_TOKEN")
    recipient, sender = recipient or os.getenv("ADMIN_PHONE"), os.getenv("TWILIO_FROM")
    if not all((sid, token, recipient, sender)):
        return "not_configured"
    when = datetime.now().astimezone().strftime("%d/%m/%Y %H:%M:%S %Z")
    offset = f" Mốc video: {event['media_offset_seconds']}s." if event.get("media_offset_seconds") is not None else ""
    response = requests.post(f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json", auth=(sid, token), data={"From": sender, "To": recipient, "Body": f"SchoolGuard: {event['object_type']} vào {event['zone_name']} lúc {when}.{offset}"}, timeout=15)
    response.raise_for_status()
    return "sent"


def _save_detection_event(db, event, source_type, source_id, image_path):
    record = DetectionEventDB(source_type=source_type, source_id=source_id, zone_id=str(event["zone_id"]), zone_name=event["zone_name"], object_type=event["object_type"], track_id=event.get("track_id"), occurred_at=datetime.now(), media_offset_seconds=event.get("media_offset_seconds"), image_path=str(image_path))
    db.add(record)
    db.flush()
    db.add(
        EventActivityDB(
            event_id=record.id,
            actor="system",
            action="Phát hiện sự kiện",
            status=record.status,
        )
    )
    db.commit()
    event["event_id"] = record.id
    event["occurred_at"] = record.occurred_at.astimezone().isoformat()
    return record


def _stored_upload_path(raw_path: str) -> Path:
    """Resolve a stored evidence path without allowing files outside uploads/."""
    image_path = Path(raw_path).resolve()
    try:
        image_path.relative_to(UPLOAD_DIR.resolve())
    except ValueError as error:
        raise HTTPException(status_code=400, detail="Đường dẫn ảnh sự kiện không hợp lệ") from error
    return image_path


def _discard_event_evidence(raw_path) -> None:
    try:
        _stored_upload_path(str(raw_path)).unlink(missing_ok=True)
    except (HTTPException, OSError):
        logger.warning("Could not discard orphaned event evidence")


def _remove_video_artifacts(output_path: Path) -> None:
    resolved = output_path.resolve()
    try:
        resolved.relative_to(UPLOAD_DIR.resolve())
    except ValueError:
        logger.error("Refused to clean video outside uploads: %s", resolved)
        return
    resolved.unlink(missing_ok=True)
    run_dir = resolved.parent
    try:
        run_dir.relative_to(VIDEO_RUNS_DIR.resolve())
    except ValueError:
        return
    for name in ("annotated.raw.mp4", "config.json", "events.jsonl", "frames.jsonl", "summary.json", "failure.json"):
        (run_dir / name).unlink(missing_ok=True)


def _cleanup_video_results() -> None:
    now = datetime.now(UTC)
    paths_to_remove = []
    with video_results_lock:
        removable = {
            video_id: result
            for video_id, result in video_results.items()
            if video_id not in active_video_downloads
        }
        expired = [
            video_id
            for video_id, result in removable.items()
            if now - result["created_at"] > VIDEO_RESULT_TTL
        ]
        overflow = max(0, len(video_results) - MAX_VIDEO_RESULTS)
        oldest = sorted(removable, key=lambda key: removable[key]["created_at"])[:overflow]
        for video_id in dict.fromkeys([*expired, *oldest]):
            result = video_results.pop(video_id, None)
            if result:
                paths_to_remove.append(result["output_path"])
    for output_path in paths_to_remove:
        _remove_video_artifacts(output_path)


def _cleanup_stale_video_artifacts() -> None:
    cutoff = datetime.now(UTC).timestamp() - VIDEO_RESULT_TTL.total_seconds()
    candidates = [*UPLOAD_DIR.glob("analysis_*"), *UPLOAD_DIR.glob(".*_input*")]
    if VIDEO_RUNS_DIR.is_dir():
        for run_dir in VIDEO_RUNS_DIR.iterdir():
            if run_dir.is_dir():
                failure_marker = run_dir / "failure.json"
                try:
                    is_stale_failure = (
                        failure_marker.is_file()
                        and failure_marker.stat().st_mtime < cutoff
                    )
                    run_dir.resolve().relative_to(VIDEO_RUNS_DIR.resolve())
                    if is_stale_failure:
                        shutil.rmtree(run_dir)
                        continue
                except (OSError, ValueError):
                    logger.warning("Could not clean failed video run: %s", run_dir.name)
                    continue
                candidates.extend(
                    run_dir / name
                    for name in (
                        "annotated.mp4",
                        "annotated.raw.mp4",
                        "config.json",
                        "events.jsonl",
                        "frames.jsonl",
                        "summary.json",
                        "failure.json",
                    )
                )
    for path in candidates:
        try:
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
        except OSError:
            logger.warning("Could not clean stale artifact: %s", path.name)


def _finish_video_download(video_id: str) -> None:
    with video_results_lock:
        active_video_downloads.discard(video_id)
    _cleanup_video_results()


_cleanup_stale_video_artifacts()


def _prune_auth_state(now: datetime) -> None:
    for token, expires_at in list(active_tokens.items()):
        if expires_at <= now:
            active_tokens.pop(token, None)
            token_usernames.pop(token, None)
    cutoff = monotonic() - LOGIN_WINDOW_SECONDS
    for key, attempts in list(login_failures.items()):
        recent = [attempt for attempt in attempts if attempt >= cutoff]
        if recent:
            login_failures[key] = recent
        else:
            login_failures.pop(key, None)


def _parse_zones(raw):
    try:
        zones = json.loads(raw or "[]")
    except json.JSONDecodeError as error:
        raise HTTPException(status_code=422, detail="Dữ liệu vùng không hợp lệ") from error
    if not isinstance(zones, list) or len(zones) > 20:
        raise HTTPException(status_code=422, detail="Tối đa 20 vùng mỗi lần phân tích")
    allowed_classes = {0, 1, 2, 3, 5, 7}
    for index, zone in enumerate(zones):
        if not isinstance(zone, dict):
            raise HTTPException(status_code=422, detail="Cấu hình vùng không hợp lệ")
        try:
            x, y, width, height = (float(zone[k]) for k in ("x", "y", "width", "height"))
            classes = [int(value) for value in zone.get("classes", list(allowed_classes))]
        except (KeyError, TypeError, ValueError) as error:
            raise HTTPException(status_code=422, detail=f"Thiếu tọa độ hoặc loại đối tượng ở vùng {index + 1}") from error
        if not (0 <= x < 1 and 0 <= y < 1 and 0 < width <= 1 - x and 0 < height <= 1 - y):
            raise HTTPException(status_code=422, detail=f"Tọa độ vùng {index + 1} phải nằm trong khung hình")
        if not classes or any(value not in allowed_classes for value in classes):
            raise HTTPException(status_code=422, detail=f"Chọn ít nhất một loại đối tượng hợp lệ ở vùng {index + 1}")
        zone.update({"x": x, "y": y, "width": width, "height": height, "classes": classes, "id": str(zone.get("id") or f"zone-{index + 1}"), "name": str(zone.get("name") or f"Vùng {index + 1}")})
    return zones


def _account_notification_settings(db, token):
    username = token_usernames.get(token)
    if not username:
        return None
    return db.query(NotificationSettingsDB).filter(NotificationSettingsDB.username == username).first()


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), 200_000).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        salt, expected = stored_hash.split("$", 1)
        actual = hash_password(password, salt).split("$", 1)[1]
        return secrets.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


with SessionLocal() as db:
    admin_username = os.getenv("SCHOOLGUARD_ADMIN_USER", "admin")
    admin_password = os.getenv("SCHOOLGUARD_ADMIN_PASSWORD")
    if (
        not admin_password
        or len(admin_password) < 12
        or admin_password == "replace-with-your-own-long-password"
    ):
        raise RuntimeError(
            "Set SCHOOLGUARD_ADMIN_PASSWORD to at least 12 characters in .env before starting"
        )
    admin_user = db.query(UserDB).filter(UserDB.username == admin_username).first()
    if admin_user is None:
        db.add(UserDB(username=admin_username, password_hash=hash_password(admin_password), role="admin"))
        db.commit()
    elif not verify_password(admin_password, admin_user.password_hash):
        # The environment file is the source of truth for this single-user local MVP.
        admin_user.password_hash = hash_password(admin_password)
        db.commit()


class AlertResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    camera_id: str
    zone_name: str
    location: str
    timestamp: datetime
    image_url: str
    evidence_image_url: str
    status: str

class StatusUpdateRequest(BaseModel):
    status: str


class DetectionEventUpdateRequest(BaseModel):
    status: str = Field(min_length=1, max_length=40)
    note: str | None = Field(default=None, max_length=1000)


class CameraCreate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    zone_id: int | None = None
    stream_url: str | None = None


class CameraResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    name: str
    zone_id: int | None
    stream_url: str | None
    status: str

class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None


class ZoneResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    description: str | None

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@app.get("/", include_in_schema=False)
def get_web_application():
    return FileResponse(BASE_DIR / "index.html", media_type="text/html")


@app.get("/local", include_in_schema=False)
def get_browser_only_application():
    if os.getenv("ENABLE_BROWSER_ONLY_MODE", "false").lower() != "true":
        raise HTTPException(status_code=404, detail="Chế độ browser-only chưa được bật")
    return FileResponse(BASE_DIR / "local" / "index.html", media_type="text/html")


@app.get("/app.js", include_in_schema=False)
def get_browser_only_script():
    return FileResponse(BASE_DIR / "app.js", media_type="text/javascript")


@app.get("/style.css", include_in_schema=False)
def get_browser_only_styles():
    return FileResponse(BASE_DIR / "style.css", media_type="text/css")


@app.get("/api/health")
def get_health():
    return {"status": "ok", "mode": "home-monitor", "sources": ["video", "webcam"]}


@app.get("/api/test-videos")
def list_test_videos():
    return {"videos": [name for name in TEST_VIDEO_NAMES if (TEST_VIDEO_DIR / name).is_file()]}


@app.get("/api/test-videos/{video_name}")
def get_test_video(video_name: str):
    if video_name not in TEST_VIDEO_NAMES:
        raise HTTPException(status_code=404, detail="Không tìm thấy video mẫu")
    video_path = TEST_VIDEO_DIR / video_name
    if not video_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy video mẫu")
    return FileResponse(video_path, media_type="video/mp4", filename=video_name)


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def require_token(token: str = Depends(oauth2_scheme)):
    now = datetime.now(UTC)
    with auth_lock:
        _prune_auth_state(now)
        expires_at = active_tokens.get(token)
        if expires_at is None:
            raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn", headers={"WWW-Authenticate": "Bearer"})
    return token


@app.post("/token")
def login(request: Request, form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    username = form_data.username[:100]
    client_host = request.client.host if request.client else "unknown"
    failure_key = (client_host, username.casefold())
    with auth_lock:
        _prune_auth_state(datetime.now(UTC))
        if len(login_failures.get(failure_key, [])) >= MAX_LOGIN_ATTEMPTS:
            raise HTTPException(status_code=429, detail="Đăng nhập quá nhiều lần. Hãy thử lại sau một phút.")
    if len(form_data.username) > 100 or len(form_data.password) > 256:
        raise HTTPException(status_code=401, detail="Sai tài khoản hoặc mật khẩu")
    user = db.query(UserDB).filter(UserDB.username == username).first()
    if user is None or not verify_password(form_data.password, user.password_hash):
        with auth_lock:
            login_failures.setdefault(failure_key, []).append(monotonic())
        raise HTTPException(status_code=401, detail="Sai tài khoản hoặc mật khẩu", headers={"WWW-Authenticate": "Bearer"})
    token = secrets.token_urlsafe(32)
    with auth_lock:
        login_failures.pop(failure_key, None)
        for old_token, token_username in list(token_usernames.items()):
            if token_username == user.username:
                active_tokens.pop(old_token, None)
                token_usernames.pop(old_token, None)
        active_tokens[token] = datetime.now(UTC) + TOKEN_TTL
        token_usernames[token] = user.username
    return {"access_token": token, "token_type": "bearer"}


class NotificationSettingsRequest(BaseModel):
    email: str | None = Field(default=None, max_length=320)
    phone: str | None = Field(default=None, max_length=40)
    channel: str = Field(default="none", max_length=10)


def _serialize_notification_settings(settings):
    return {
        "email": settings.email or "",
        "phone": settings.phone or "",
        "channel": settings.channel,
    }


@app.get("/api/account/notifications")
def get_notification_settings(db: Session = Depends(get_db), token: str = Depends(require_token)):
    settings = _account_notification_settings(db, token)
    if settings is None:
        return {"email": "", "phone": "", "channel": "none"}
    return _serialize_notification_settings(settings)


@app.get("/api/account/notifications/status")
def get_notification_provider_status(db: Session = Depends(get_db), token: str = Depends(require_token)):
    settings = _account_notification_settings(db, token)
    email_recipient = (settings.email if settings else None) or os.getenv("ADMIN_EMAIL", "")
    phone_recipient = (settings.phone if settings else None) or os.getenv("ADMIN_PHONE", "")
    smtp_ready = all(os.getenv(key) for key in ("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD"))
    twilio_ready = all(os.getenv(key) for key in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM"))
    return {
        "email_ready": bool(email_recipient and smtp_ready),
        "email_recipient_set": bool(email_recipient),
        "smtp_ready": smtp_ready,
        "sms_ready": bool(phone_recipient and twilio_ready),
        "phone_recipient_set": bool(phone_recipient),
        "twilio_ready": twilio_ready,
    }


@app.put("/api/account/notifications")
def save_notification_settings(request: NotificationSettingsRequest, db: Session = Depends(get_db), token: str = Depends(require_token)):
    email = (request.email or "").strip()
    phone = (request.phone or "").strip()
    channel = request.channel.lower().strip()
    if channel not in {"none", "email", "sms", "both"}:
        raise HTTPException(status_code=422, detail="Kênh phải là none, email, sms hoặc both")
    if email and ("@" not in email or email.startswith("@") or email.endswith("@")):
        raise HTTPException(status_code=422, detail="Địa chỉ email không hợp lệ")
    if phone and any(char not in "+0123456789 ()-" for char in phone):
        raise HTTPException(status_code=422, detail="Số điện thoại chỉ được chứa chữ số và + ( ) -")
    if channel in {"email", "both"} and not email:
        raise HTTPException(status_code=422, detail="Nhập Gmail để bật cảnh báo email")
    if channel in {"sms", "both"} and not phone:
        raise HTTPException(status_code=422, detail="Nhập số điện thoại để bật SMS")
    username = token_usernames[token]
    settings = _account_notification_settings(db, token)
    if settings is None:
        settings = NotificationSettingsDB(username=username)
        db.add(settings)
    settings.email = email or None
    settings.phone = phone or None
    settings.channel = channel
    db.commit()
    db.refresh(settings)
    return _serialize_notification_settings(settings)


@app.post("/api/zones", response_model=ZoneResponse, status_code=201)
def create_zone(zone: ZoneCreate, db: Session = Depends(get_db), _: str = Depends(require_token)):
    if db.query(ZoneDB).filter(ZoneDB.name == zone.name).first():
        raise HTTPException(status_code=409, detail="Tên khu vực đã tồn tại")
    record = ZoneDB(name=zone.name.strip(), description=zone.description)
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.get("/api/zones", response_model=list[ZoneResponse])
def get_zones(db: Session = Depends(get_db), _: str = Depends(require_token)):
    return db.query(ZoneDB).order_by(ZoneDB.name).all()


@app.post("/api/cameras", response_model=CameraResponse, status_code=201)
def create_camera(camera: CameraCreate, db: Session = Depends(get_db), _: str = Depends(require_token)):
    if db.query(CameraDB).filter(CameraDB.id == camera.id).first():
        raise HTTPException(status_code=409, detail="Camera ID đã tồn tại")
    if camera.zone_id is not None and not db.query(ZoneDB).filter(ZoneDB.id == camera.zone_id).first():
        raise HTTPException(status_code=404, detail="Không tìm thấy khu vực")
    record = CameraDB(**camera.dict())
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


@app.get("/api/cameras", response_model=list[CameraResponse])
def get_cameras(db: Session = Depends(get_db), _: str = Depends(require_token)):
    return db.query(CameraDB).order_by(CameraDB.id).all()


@app.post("/api/alerts", response_model=AlertResponse, status_code=201)
async def create_alert(
    camera_id: str = Form(..., min_length=1, max_length=100),
    zone_name: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    extension = ALLOWED_IMAGE_TYPES.get(file.content_type or "")
    if extension is None:
        raise HTTPException(status_code=415, detail="Chỉ chấp nhận ảnh JPEG, PNG hoặc WebP")

    file_name = f"alert_{secrets.token_hex(16)}{extension}"
    file_path = UPLOAD_DIR / file_name
    size = 0
    try:
        with file_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="Ảnh vượt quá giới hạn 10 MB")
                await run_in_threadpool(destination.write, chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="File ảnh rỗng")
        decoded_image = await run_in_threadpool(cv2.imread, str(file_path))
        if decoded_image is None:
            raise HTTPException(status_code=415, detail="Nội dung file không phải ảnh hợp lệ")
        if decoded_image.shape[1] > 1920 or decoded_image.shape[0] > 1080:
            raise HTTPException(status_code=413, detail="Ảnh vượt quá độ phân giải Full HD")

        record = AlertDB(camera_id=camera_id.strip(), zone_name=zone_name.strip(), image_url=file_name)
        db.add(record)
        db.commit()
        db.refresh(record)
        return serialize_alert(record)
    except Exception:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise
    finally:
        await file.close()


@app.get("/api/alerts", response_model=list[AlertResponse])
def get_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: str | None = Query(None, max_length=50),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    query = db.query(AlertDB)
    if status:
        query = query.filter(AlertDB.status == status)
    records = query.order_by(AlertDB.timestamp.desc(), AlertDB.id.desc()).offset(skip).limit(limit).all()
    return [serialize_alert(alert) for alert in records]


@app.get("/api/alerts/{alert_id}/image")
def get_alert_image(alert_id: int, db: Session = Depends(get_db), _: str = Depends(require_token)):
    alert = db.query(AlertDB).filter(AlertDB.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo")
    image_path = UPLOAD_DIR / Path(alert.image_url).name
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh cảnh báo")
    return FileResponse(image_path)


@app.put("/api/alerts/{alert_id}/status", response_model=AlertResponse)
def update_alert_status(
    alert_id: int,
    request: StatusUpdateRequest,
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    valid_statuses = {"Mới", "Đang xử lý", "Đã xử lý"}
    if request.status not in valid_statuses:
        raise HTTPException(status_code=422, detail="Trạng thái phải là Mới, Đang xử lý hoặc Đã xử lý")
    alert = db.query(AlertDB).filter(AlertDB.id == alert_id).first()
    if alert is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy cảnh báo")
    alert.status = request.status
    db.commit()
    db.refresh(alert)
    return serialize_alert(alert)


@app.post("/api/videos/analyze")
async def analyze_uploaded_video(
    file: UploadFile = File(...),
    zones: str = Form("[]"),
    db: Session = Depends(get_db),
    token: str = Depends(require_token),
):
    _cleanup_video_results()
    selected_zones = _parse_zones(zones)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Chọn video MP4, MOV, AVI, MKV hoặc WebM")

    video_id = secrets.token_hex(12)
    input_path = UPLOAD_DIR / f".{video_id}_input{extension}"
    output_path = UPLOAD_DIR / f"analysis_{video_id}.webm"
    result_output_path = output_path
    size = 0
    try:
        with input_path.open("wb") as destination:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_VIDEO_BYTES:
                    raise HTTPException(status_code=413, detail="Video vượt quá giới hạn 300 MB")
                await run_in_threadpool(destination.write, chunk)
        if size == 0:
            raise HTTPException(status_code=400, detail="File video rỗng")

        try:
            await run_in_threadpool(validate_video_duration, input_path, max_seconds=180)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        if not video_analysis_lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Một video khác đang được phân tích. Hãy thử lại sau.")
        try:
            try:
                if can_use_person_worker(selected_zones):
                    summary = await run_in_threadpool(
                        analyze_person_video,
                        input_path,
                        VIDEO_RUNS_DIR,
                        selected_zones,
                        source_id=Path(file.filename or "video").name,
                    )
                    result_output_path = summary.pop("output_path")
                else:
                    summary = await run_in_threadpool(
                        analyze_video, str(input_path), str(output_path), selected_zones
                    )
            finally:
                video_analysis_lock.release()
        except ValueError as error:
            output_path.unlink(missing_ok=True)
            logger.warning("Video decoding/analysis rejected: %s", type(error).__name__)
            raise HTTPException(status_code=422, detail="Video không hợp lệ hoặc không thể giải mã") from error
        except ImportError as error:
            output_path.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail="Thiếu thư viện nhận diện. Cài các gói trong requirements.txt") from error
        except Exception as error:
            output_path.unlink(missing_ok=True)
            logger.exception("Video analysis failed")
            raise HTTPException(status_code=500, detail="Phân tích video thất bại") from error

        for event in summary.get("events", []):
            try:
                _save_detection_event(db, event, "video", Path(file.filename or "video").name, event["image_path"])
            except Exception:
                db.rollback()
                logger.exception("Could not persist video event")
                _discard_event_evidence(event.get("image_path"))
                event["notification_status"] = "save_failed"
                event.pop("image_path", None)
                continue

            settings = _account_notification_settings(db, token)
            notify_channel = settings.channel if settings else os.getenv("CAMERA_NOTIFY_CHANNEL", "none").lower()
            recipient_email = settings.email if settings and settings.email else os.getenv("ADMIN_EMAIL")
            recipient_phone = settings.phone if settings and settings.phone else os.getenv("ADMIN_PHONE")
            statuses = []
            if notify_channel in {"email", "both"}:
                try:
                    statuses.append(await run_in_threadpool(_send_event_email, event, event["image_path"], recipient_email))
                except Exception as error:
                    logger.warning("Email notification failed: %s", type(error).__name__)
                    statuses.append("email_failed")
            if notify_channel in {"sms", "both"}:
                try:
                    statuses.append(await run_in_threadpool(_send_camera_sms, event, recipient_phone))
                except Exception as error:
                    logger.warning("SMS notification failed: %s", type(error).__name__)
                    statuses.append("sms_failed")
            event["notification_status"] = ",".join(statuses) if statuses else "disabled"
            event.pop("image_path", None)
        with video_results_lock:
            video_results[video_id] = {
                "summary": summary,
                "output_path": result_output_path,
                "created_at": datetime.now(UTC),
            }
        _cleanup_video_results()
        return {
            "video_id": video_id,
            "video_name": Path(file.filename or "video").name,
            **summary,
            "annotated_video_url": f"/api/videos/{video_id}/annotated",
            "annotated_video_filename": f"schoolguard_{video_id}{result_output_path.suffix}",
        }
    except HTTPException:
        _remove_video_artifacts(result_output_path)
        raise
    finally:
        input_path.unlink(missing_ok=True)
        await file.close()


@app.get("/api/videos/{video_id}/annotated")
def get_annotated_video(video_id: str, _: str = Depends(require_token)):
    _cleanup_video_results()
    with video_results_lock:
        result = video_results.get(video_id)
        if result is not None:
            active_video_downloads.add(video_id)
    if result is None or not result["output_path"].is_file():
        with video_results_lock:
            active_video_downloads.discard(video_id)
        raise HTTPException(status_code=404, detail="Không tìm thấy video đã phân tích; hãy chạy phân tích lại")
    output_path = result["output_path"]
    media_type = mimetypes.guess_type(output_path.name)[0] or "application/octet-stream"
    return FileResponse(
        output_path,
        media_type=media_type,
        filename=f"schoolguard_{video_id}{output_path.suffix}",
        background=BackgroundTask(_finish_video_download, video_id),
    )


@app.post("/api/live/detect")
async def detect_live_camera_frame(
    file: UploadFile = File(...),
    zones: str = Form("[]"),
    stream_id: str = Form("default", min_length=1, max_length=100),
    source_name: str = Form("Camera trực tiếp", min_length=1, max_length=200),
    source_type: str = Form("camera"),
    media_offset_seconds: float | None = Form(None, ge=0),
    selected_classes: str = Form("[0]"),
    db: Session = Depends(get_db),
    token: str = Depends(require_token),
):
    if source_type not in {"camera", "video"}:
        raise HTTPException(status_code=422, detail="Nguồn nhận diện không hợp lệ")
    if file.content_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise HTTPException(status_code=415, detail="Khung hình camera phải là ảnh JPEG, PNG hoặc WebP")
    frame_bytes = await file.read(3 * 1024 * 1024 + 1)
    await file.close()
    if len(frame_bytes) > 3 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Khung hình vượt quá 3 MB")
    try:
        selected_zones = _parse_zones(zones)
        try:
            classes = json.loads(selected_classes)
            if (
                not isinstance(classes, list)
                or not classes
                or any(type(value) is not int or value not in {0, 1, 2, 3, 5, 7} for value in classes)
            ):
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=422, detail="Danh sách loại đối tượng không hợp lệ")
        zone_classes = sorted({class_id for zone in selected_zones for class_id in zone["classes"]})
        inference_classes = zone_classes or classes
        if not live_detection_lock.acquire(blocking=False):
            raise HTTPException(status_code=429, detail="Máy đang xử lý một khung hình khác. Hãy thử lại.")
        try:
            result = await run_in_threadpool(
                detect_live_frame_jpeg,
                frame_bytes,
                selected_zones,
                stream_id,
                inference_classes,
            )
        finally:
            live_detection_lock.release()
        new_events = result.get("events", [])
        result["events"] = []
        settings = _account_notification_settings(db, token)
        notify_channel = settings.channel if settings else os.getenv("CAMERA_NOTIFY_CHANNEL", "none").lower()
        recipient_email = settings.email if settings else os.getenv("ADMIN_EMAIL")
        recipient_phone = settings.phone if settings else os.getenv("ADMIN_PHONE")
        for event in new_events:
            event["media_offset_seconds"] = round(media_offset_seconds, 2) if source_type == "video" and media_offset_seconds is not None else None
            image_path = UPLOAD_DIR / f"event_{source_type}_{secrets.token_hex(12)}.jpg"
            evidence = await run_in_threadpool(annotate_live_event_jpeg, frame_bytes, event, result.get("detections", []), selected_zones)
            image_path.write_bytes(evidence)
            try:
                _save_detection_event(db, event, source_type, source_name[:200], image_path)
                statuses = []
                if notify_channel in {"email", "both"}:
                    statuses.append(await run_in_threadpool(_send_event_email, event, image_path, recipient_email))
                if notify_channel in {"sms", "both"}:
                    statuses.append(await run_in_threadpool(_send_camera_sms, event, recipient_phone))
                event["notification_status"] = ",".join(statuses) if statuses else "disabled"
            except Exception as error:
                db.rollback()
                logger.warning("Live event persistence/notification failed: %s", type(error).__name__)
                if not event.get("event_id"):
                    _discard_event_evidence(image_path)
                event["notification_status"] = "failed"
            event["image_url"] = f"/api/events/{event.get('event_id')}/image" if event.get("event_id") else None
            result["events"].append(event)
        return result
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/live/streams/{stream_id}")
def delete_live_stream(
    stream_id: str,
    _: str = Depends(require_token),
):
    if not stream_id or len(stream_id) > 100:
        raise HTTPException(status_code=422, detail="Mã luồng không hợp lệ")
    return {"released": release_live_stream(stream_id)}


def _local_isoformat(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.astimezone()
    return value.isoformat()


def _serialize_detection_event(event: DetectionEventDB) -> dict:
    return {
        "id": event.id,
        "source_type": event.source_type,
        "source_id": event.source_id,
        "zone_id": event.zone_id,
        "zone_name": event.zone_name,
        "location": event.zone_name,
        "object_type": event.object_type,
        "track_id": event.track_id,
        "occurred_at": _local_isoformat(event.occurred_at),
        "media_offset_seconds": event.media_offset_seconds,
        "image_url": f"/api/events/{event.id}/image",
        "status": event.status or EVENT_STATUSES[0],
        "note": event.note or "",
        "activities": [
            {
                "id": activity.id,
                "occurred_at": _local_isoformat(activity.occurred_at),
                "actor": activity.actor,
                "action": activity.action,
                "status": activity.status,
                "note": activity.note or "",
            }
            for activity in event.activities[-50:]
        ],
    }


@app.get("/api/events/{event_id}/image")
def get_detection_event_image(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_token)):
    event = db.query(DetectionEventDB).filter(DetectionEventDB.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh sự kiện")
    image_path = _stored_upload_path(event.image_path)
    if not image_path.is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh sự kiện")
    return FileResponse(image_path, media_type="image/jpeg")


@app.put("/api/events/{event_id}/status")
def update_detection_event_status(
    event_id: int,
    update: DetectionEventUpdateRequest,
    db: Session = Depends(get_db),
    token: str = Depends(require_token),
):
    event = db.query(DetectionEventDB).filter(DetectionEventDB.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện")

    status = update.status.strip()
    if status not in EVENT_STATUSES:
        raise HTTPException(
            status_code=422,
            detail=f"Trạng thái phải là một trong: {', '.join(EVENT_STATUSES)}",
        )
    note = (update.note or "").strip()
    if event.status == status and (event.note or "") == note:
        return _serialize_detection_event(event)
    with auth_lock:
        actor = token_usernames.get(token)
    if actor is None:
        raise HTTPException(status_code=401, detail="Phiên đăng nhập đã thay đổi; hãy đăng nhập lại")
    event.status = status
    event.note = note or None
    db.add(
        EventActivityDB(
            event_id=event.id,
            actor=actor,
            action=f"Cập nhật trạng thái: {status}",
            status=status,
            note=note or None,
        )
    )
    db.commit()
    db.refresh(event)
    return _serialize_detection_event(event)


@app.delete("/api/events/{event_id}")
def delete_detection_event(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_token)):
    event = db.query(DetectionEventDB).filter(DetectionEventDB.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện")

    image_path = _stored_upload_path(event.image_path)

    db.delete(event)
    db.commit()
    try:
        image_path.unlink(missing_ok=True)
    except OSError:
        logger.warning("Event %s deleted but its evidence file could not be removed", event_id)
    return {"message": "Đã xóa sự kiện", "id": event_id}


@app.get("/api/events")
def get_detection_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    q: str | None = Query(None, max_length=200),
    status: str | None = Query(None, max_length=40),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    query = db.query(DetectionEventDB)
    if status:
        if status not in EVENT_STATUSES:
            raise HTTPException(status_code=422, detail="Bộ lọc trạng thái không hợp lệ")
        query = query.filter(DetectionEventDB.status == status)
    if q and q.strip():
        raw_term = q.strip()
        term = f"%{raw_term}%"
        filters = [
            DetectionEventDB.zone_name.ilike(term),
            DetectionEventDB.object_type.ilike(term),
            DetectionEventDB.source_id.ilike(term),
            DetectionEventDB.source_type.ilike(term),
            DetectionEventDB.status.ilike(term),
            DetectionEventDB.note.ilike(term),
        ]
        if raw_term.isdigit():
            filters.extend([DetectionEventDB.id == int(raw_term), DetectionEventDB.track_id == int(raw_term)])
        query = query.filter(or_(*filters))
    records = query.order_by(DetectionEventDB.occurred_at.desc(), DetectionEventDB.id.desc()).offset(skip).limit(limit).all()
    return [_serialize_detection_event(event) for event in records]


@app.get("/api/dashboard/summary")
def get_dashboard_summary(db: Session = Depends(get_db), _: str = Depends(require_token)):
    events = db.query(DetectionEventDB).all()
    today = datetime.now().astimezone().date()
    source_counts = {"video": 0, "camera": 0}
    today_events = 0
    for event in events:
        source_counts[event.source_type] = source_counts.get(event.source_type, 0) + 1
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.astimezone()
        if occurred_at.astimezone().date() == today:
            today_events += 1

    return {
        "total_events": len(events),
        "today_events": today_events,
        "sources": source_counts,
        "stored_alerts": db.query(AlertDB).count(),
    }
