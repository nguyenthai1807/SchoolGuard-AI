import os
import hashlib
import json
import secrets
import smtplib
import requests
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from pathlib import Path
from typing import List, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, create_engine, or_
from sqlalchemy.orm import Session, declarative_base, relationship, sessionmaker
from starlette.concurrency import run_in_threadpool
from video_analysis import analyze_video, annotate_live_event_jpeg, detect_live_frame_jpeg


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


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./schoolguard.db")
engine_options = {"connect_args": {"check_same_thread": False}} if DATABASE_URL.startswith("sqlite") else {}
engine = create_engine(DATABASE_URL, **engine_options)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

UPLOAD_DIR = Path(os.getenv("UPLOAD_DIR", "uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_VIDEO_BYTES = 300 * 1024 * 1024
ALLOWED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
TOKEN_TTL = timedelta(hours=8)
active_tokens = {}
token_usernames = {}
video_results = {}

app = FastAPI(title="SchoolGuard AI Backend")
allowed_origins = [
    origin.strip()
    for origin in os.getenv(
        "FRONTEND_ORIGINS",
        "http://localhost:3000,http://localhost:5173,http://localhost:5500,http://127.0.0.1:5500",
    ).split(",")
    if origin.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)


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
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    else:
        timestamp = timestamp.astimezone(timezone.utc)
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
    db.commit()
    event["event_id"] = record.id
    event["occurred_at"] = record.occurred_at.astimezone().isoformat()
    return record


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


def hash_password(password: str, salt: Optional[str] = None) -> str:
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
    admin_password = os.getenv("SCHOOLGUARD_ADMIN_PASSWORD", "123456")
    if db.query(UserDB).filter(UserDB.username == admin_username).first() is None:
        db.add(UserDB(username=admin_username, password_hash=hash_password(admin_password), role="admin"))
        db.commit()


class AlertResponse(BaseModel):
    id: int
    camera_id: str
    zone_name: str
    location: str
    timestamp: datetime
    image_url: str
    evidence_image_url: str
    status: str

    class Config:
        orm_mode = True


class StatusUpdateRequest(BaseModel):
    status: str


class CameraCreate(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    zone_id: Optional[int] = None
    stream_url: Optional[str] = None


class CameraResponse(BaseModel):
    id: str
    name: str
    zone_id: Optional[int]
    stream_url: Optional[str]
    status: str

    class Config:
        orm_mode = True


class ZoneCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None


class ZoneResponse(BaseModel):
    id: int
    name: str
    description: Optional[str]

    class Config:
        orm_mode = True


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/token")


def require_token(token: str = Depends(oauth2_scheme)):
    expires_at = active_tokens.get(token)
    if expires_at is None or expires_at <= datetime.utcnow():
        active_tokens.pop(token, None)
        token_usernames.pop(token, None)
        raise HTTPException(status_code=401, detail="Token không hợp lệ hoặc đã hết hạn", headers={"WWW-Authenticate": "Bearer"})
    return token


@app.post("/token")
def login(form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    user = db.query(UserDB).filter(UserDB.username == form_data.username).first()
    if user is None or not verify_password(form_data.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Sai tài khoản hoặc mật khẩu", headers={"WWW-Authenticate": "Bearer"})
    token = secrets.token_urlsafe(32)
    active_tokens[token] = datetime.utcnow() + TOKEN_TTL
    token_usernames[token] = user.username
    return {"access_token": token, "token_type": "bearer"}


class NotificationSettingsRequest(BaseModel):
    email: Optional[str] = Field(default=None, max_length=320)
    phone: Optional[str] = Field(default=None, max_length=40)
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


@app.get("/api/zones", response_model=List[ZoneResponse])
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


@app.get("/api/cameras", response_model=List[CameraResponse])
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


@app.get("/api/alerts", response_model=List[AlertResponse])
def get_alerts(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    status: Optional[str] = Query(None, max_length=50),
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
    selected_zones = _parse_zones(zones)
    extension = Path(file.filename or "").suffix.lower()
    if extension not in ALLOWED_VIDEO_EXTENSIONS:
        raise HTTPException(status_code=415, detail="Chọn video MP4, MOV, AVI, MKV hoặc WebM")

    video_id = secrets.token_hex(12)
    input_path = UPLOAD_DIR / f".{video_id}_input{extension}"
    output_path = UPLOAD_DIR / f"analysis_{video_id}.webm"
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
            summary = await run_in_threadpool(analyze_video, str(input_path), str(output_path), selected_zones)
        except ValueError as error:
            output_path.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=str(error)) from error
        except ImportError as error:
            output_path.unlink(missing_ok=True)
            raise HTTPException(status_code=503, detail="Thiếu thư viện nhận diện. Cài các gói trong requirements.txt") from error
        except Exception as error:
            output_path.unlink(missing_ok=True)
            raise HTTPException(status_code=500, detail=f"Phân tích video thất bại: {error}") from error

        for event in summary.get("events", []):
            try:
                _save_detection_event(db, event, "video", Path(file.filename or "video").name, event["image_path"])
            except Exception as error:
                event["notification_status"] = f"save_failed: {error}"
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
                    statuses.append(f"email_failed: {error}")
            if notify_channel in {"sms", "both"}:
                try:
                    statuses.append(await run_in_threadpool(_send_camera_sms, event, recipient_phone))
                except Exception as error:
                    statuses.append(f"sms_failed: {error}")
            event["notification_status"] = ",".join(statuses) if statuses else "disabled"
            event.pop("image_path", None)
        video_results[video_id] = {"summary": summary, "output_path": output_path}
        return {
            "video_id": video_id,
            "video_name": Path(file.filename or "video").name,
            **summary,
            "annotated_video_url": f"/api/videos/{video_id}/annotated",
        }
    except HTTPException:
        output_path.unlink(missing_ok=True)
        raise
    finally:
        input_path.unlink(missing_ok=True)
        await file.close()


@app.get("/api/videos/{video_id}/annotated")
def get_annotated_video(video_id: str, _: str = Depends(require_token)):
    result = video_results.get(video_id)
    if result is None or not result["output_path"].is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy video đã phân tích; hãy chạy phân tích lại")
    return FileResponse(result["output_path"], media_type="video/webm", filename=f"schoolguard_{video_id}.webm")


@app.post("/api/live/detect")
async def detect_live_camera_frame(
    file: UploadFile = File(...),
    zones: str = Form("[]"),
    stream_id: str = Form("default"),
    source_name: str = Form("Camera trực tiếp"),
    source_type: str = Form("camera"),
    media_offset_seconds: Optional[float] = Form(None, ge=0),
    selected_classes: str = Form("[0,1,2,3,5,7]"),
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
            if not isinstance(classes, list):
                raise ValueError()
        except (json.JSONDecodeError, ValueError):
            raise HTTPException(status_code=422, detail="Danh sách loại đối tượng không hợp lệ")
        zone_classes = sorted({class_id for zone in selected_zones for class_id in zone["classes"]})
        inference_classes = zone_classes or [0, 1, 2, 3, 5, 7]
        result = await run_in_threadpool(detect_live_frame_jpeg, frame_bytes, selected_zones, stream_id, inference_classes)
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
                event["notification_status"] = f"failed: {error}"
            event["image_url"] = f"/api/events/{event.get('event_id')}/image" if event.get("event_id") else None
            result["events"].append(event)
        return result
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.get("/api/events/{event_id}/image")
def get_detection_event_image(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_token)):
    event = db.query(DetectionEventDB).filter(DetectionEventDB.id == event_id).first()
    if event is None or not Path(event.image_path).is_file():
        raise HTTPException(status_code=404, detail="Không tìm thấy ảnh sự kiện")
    return FileResponse(event.image_path, media_type="image/jpeg")


@app.delete("/api/events/{event_id}")
def delete_detection_event(event_id: int, db: Session = Depends(get_db), _: str = Depends(require_token)):
    event = db.query(DetectionEventDB).filter(DetectionEventDB.id == event_id).first()
    if event is None:
        raise HTTPException(status_code=404, detail="Không tìm thấy sự kiện")

    image_path = Path(event.image_path).resolve()
    upload_root = UPLOAD_DIR.resolve()
    try:
        image_path.relative_to(upload_root)
    except ValueError:
        raise HTTPException(status_code=400, detail="Đường dẫn ảnh sự kiện không hợp lệ")

    db.delete(event)
    db.commit()
    image_path.unlink(missing_ok=True)
    return {"message": "Đã xóa sự kiện", "id": event_id}


@app.get("/api/events")
def get_detection_events(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    q: Optional[str] = Query(None, max_length=200),
    db: Session = Depends(get_db),
    _: str = Depends(require_token),
):
    query = db.query(DetectionEventDB)
    if q and q.strip():
        raw_term = q.strip()
        term = f"%{raw_term}%"
        filters = [
            DetectionEventDB.zone_name.ilike(term),
            DetectionEventDB.object_type.ilike(term),
            DetectionEventDB.source_id.ilike(term),
            DetectionEventDB.source_type.ilike(term),
        ]
        if raw_term.isdigit():
            filters.extend([DetectionEventDB.id == int(raw_term), DetectionEventDB.track_id == int(raw_term)])
        query = query.filter(or_(*filters))
    records = query.order_by(DetectionEventDB.occurred_at.desc(), DetectionEventDB.id.desc()).offset(skip).limit(limit).all()
    events = []
    for event in records:
        occurred_at = event.occurred_at
        if occurred_at.tzinfo is None:
            occurred_at = occurred_at.astimezone()
        events.append({
            "id": event.id,
            "source_type": event.source_type,
            "source_id": event.source_id,
            "zone_id": event.zone_id,
            "zone_name": event.zone_name,
            "location": event.zone_name,
            "object_type": event.object_type,
            "track_id": event.track_id,
            "occurred_at": occurred_at.isoformat(),
            "media_offset_seconds": event.media_offset_seconds,
            "image_url": f"/api/events/{event.id}/image",
        })
    return events
