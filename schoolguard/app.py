import csv
import io
import json
import secrets
import threading
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .auth import bootstrap, hash_password, make_session, token_hash, verify_password
from .config import Settings
from .db import Database, now, public_job
from .detector import PersonDetector
from .fire import FireDetector
from .live import LiveAnalyzer
from .media import Reader, index_dataset, jpeg, metadata
from .schemas import AlertUpdate, JobRequest, Login, UserCreate
from .telegram import TelegramNotifier
from .worker import Worker


def create_app(settings=None, detector_factory=None, fire_factory=None):
    settings = settings or Settings()
    settings.runtime.mkdir(parents=True, exist_ok=True)
    db = Database(settings.runtime / "schoolguard.sqlite3")
    worker = Worker(db, settings,
                    **({"detector_factory": detector_factory} if detector_factory else {}),
                    **({"fire_factory": fire_factory} if fire_factory else {}))
    live_sessions = {}
    live_lock = threading.Lock()
    notifier = TelegramNotifier()
    telegram_retry_lock = threading.Lock()
    attempts = defaultdict(deque)
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
        yield
        with live_lock:
            live_sessions.clear()
        worker.close()

    app = FastAPI(title="LH25 · Home Monitor", version="0.2.0", lifespan=lifespan)
    app.state.db = db
    app.state.worker = worker
    app.state.settings = settings
    app.state.live_sessions = live_sessions
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "testserver", "[::1]"]
    )

    @app.middleware("http")
    async def security(request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            if origin and urlparse(origin).netloc != request.headers.get("host"):
                return Response("Origin refused", status_code=403)
        result = await call_next(request)
        result.headers["X-Content-Type-Options"] = "nosniff"
        result.headers["Referrer-Policy"] = "same-origin"
        result.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' blob: data:; media-src 'self' blob:; style-src 'self'; script-src 'self'; frame-ancestors 'self'; base-uri 'self'; form-action 'self'"
        )
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
        return row

    def operator(current=Depends(user)):
        if current["role"] not in {"operator", "admin"}:
            raise HTTPException(403, "Cần quyền operator hoặc admin.")
        return current

    def admin(current=Depends(user)):
        if current["role"] != "admin":
            raise HTTPException(403, "Cần quyền admin.")
        return current

    def source(ident):
        row = db.one("SELECT * FROM sources WHERE id=?", (ident,))
        if not row:
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

    def job(ident):
        row = db.one(
            "SELECT j.*,s.name source_name FROM jobs j JOIN sources s ON s.id=j.source_id WHERE j.id=?",
            (ident,),
        )
        if not row:
            raise HTTPException(404, "Không tìm thấy tác vụ.")
        return public_job(row)

    @app.get("/api/health")
    def health():
        return {"status": "ok", "version": "0.2.0", "product": "LH25"}

    @app.post("/api/login")
    def login(payload: Login, request: Request, response: Response):
        key = request.client.host if request.client else "local"
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
        response.set_cookie("sg_session", token, httponly=True, samesite="strict", max_age=8 * 3600)
        db.audit(row["id"], "login", str(row["id"]))
        return {"id": row["id"], "username": row["username"], "role": row["role"]}

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
        return current

    @app.get("/api/users")
    def users(current=Depends(admin)):
        return db.all("SELECT id,username,role FROM users ORDER BY id")

    @app.post("/api/users", status_code=201)
    def create_user(payload: UserCreate, current=Depends(admin)):
        import sqlite3

        try:
            db.execute(
                "INSERT INTO users(username,password,role) VALUES(?,?,?)",
                (payload.username, hash_password(payload.password), payload.role),
            )
        except sqlite3.IntegrityError:
            raise HTTPException(409, "Tên đăng nhập đã tồn tại.")
        db.audit(current["id"], "create_user", payload.username, payload.role)
        return {"username": payload.username, "role": payload.role}

    @app.get("/api/system")
    def system(current=Depends(user)):
        return {
            "models": {
                name: (settings.models / (name + ".pt")).is_file()
                for name in ["yolo11n", "yolo11s", "schoolguard-person-v1", "yolo11n-pose"]
            },
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
            "telegram_configured": notifier.configured,
            "live_available": (settings.models / "yolo11n-pose.pt").is_file(),
            "detection_note": "Nhãn anomaly của ShanghaiTech không phải nhãn bounding box người. Pipeline fine-tune dùng nhãn người riêng; xem Huấn luyện AI để biết kết quả.",
        }

    @app.get("/api/stats")
    def stats(current=Depends(user)):
        return {
            "sources": db.one("SELECT count(*) n FROM sources")["n"],
            "jobs": db.all("SELECT status,count(*) count FROM jobs GROUP BY status"),
            "alerts": db.all("SELECT status,count(*) count FROM alerts GROUP BY status"),
            "latest": [
                public_job(x)
                for x in db.all(
                    "SELECT j.*,s.name source_name FROM jobs j JOIN sources s ON j.source_id=s.id ORDER BY created_at DESC,id DESC LIMIT 8"
                )
            ],
        }

    @app.get("/api/training")
    def training(current=Depends(user)):
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
        return {
            "counts": counts,
            "runs": runs,
            "report": report,
            "candidate_available": (settings.models / "schoolguard-person-v1.pt").is_file(),
            "event_dataset": events,
        }

    @app.get("/api/sources")
    def sources(
        q: str = "",
        split: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(40, ge=1, le=100),
        current=Depends(user),
    ):
        args = (f"%{q}%", split, split)
        where = "WHERE split!='live' AND name LIKE ? AND (?='' OR split=?)"
        rows = db.all(
            "SELECT id,name,kind,split FROM sources "
            + where
            + " ORDER BY split,name,id LIMIT ? OFFSET ?",
            (*args, limit, offset),
        )
        return {
            "items": rows,
            "total": db.one("SELECT count(*) n FROM sources " + where, args)["n"],
        }

    @app.get("/api/sources/{ident}")
    def source_detail(ident: str, current=Depends(user)):
        row = source(ident)
        try:
            info = metadata(row)
        except ValueError as exc:
            raise HTTPException(422, str(exc))
        return {k: v for k, v in row.items() if k != "path"} | info

    @app.get("/api/sources/{ident}/thumbnail")
    def thumbnail(ident: str, current=Depends(user)):
        row = source(ident)
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
        ident = uuid.uuid4().hex
        folder = settings.runtime / "uploads"
        folder.mkdir(exist_ok=True)
        path = folder / (ident + suffix)
        total = 0
        try:
            with path.open("wb") as target:
                while chunk := file.file.read(1024 * 1024):
                    total += len(chunk)
                    if total > settings.max_upload_bytes:
                        raise HTTPException(413, "Video vượt quá 1 GB.")
                    target.write(chunk)
            with Reader(path):
                pass
            name = Path((file.filename or "video").replace("\\", "/")).name[:150]
            db.execute(
                "INSERT INTO sources VALUES(?,?,?,?,?)",
                (ident, name, str(path.resolve()), "video", "uploaded"),
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
        source(payload.source_id)
        if not (settings.models / (payload.model + ".pt")).is_file():
            raise HTTPException(409, "Model chưa được tải. Chạy scripts/download_models.py.")
        if payload.detect_fire and not all(
            (settings.models / name).is_file() for name in ("fire-smoke-v1.onnx", "fire-model.json")
        ):
            raise HTTPException(
                409, "Chưa có model lửa/khói. Chạy python -m scripts.download_fire_model."
            )
        ident = uuid.uuid4().hex
        with db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            pending = conn.execute(
                "SELECT count(*) FROM jobs WHERE status IN ('queued','running')"
            ).fetchone()[0]
            if pending >= 10:
                raise HTTPException(429, "Hàng đợi đã đầy (10 tác vụ).")
            conn.execute(
                "INSERT INTO jobs(id,source_id,status,created_at,config,user_id) VALUES(?,?,'queued',?,?,?)",
                (ident, payload.source_id, now(), payload.model_dump_json(), current["id"]),
            )
        db.audit(current["id"], "create_job", ident)
        worker.wake.set()
        return job(ident)

    @app.post("/api/live/start", status_code=201)
    def start_live(payload: JobRequest, current=Depends(operator)):
        """Start one local webcam session using the same detector/rules as video jobs."""
        if detector_factory is None and not (settings.models / (payload.model + ".pt")).is_file():
            raise HTTPException(409, "Model chưa được tải. Chạy scripts/download_models.py.")
        if payload.detect_fire and not all(
            (settings.models / name).is_file()
            for name in ("fire-smoke-v1.onnx", "fire-model.json")
        ):
            raise HTTPException(409, "Chưa có model lửa/khói.")
        with live_lock:
            if live_sessions:
                stale = [key for key, session in live_sessions.items()
                         if time.monotonic() - session["last_seen"] > 45]
                for key in stale:
                    old = live_sessions.pop(key)
                    with old["lock"]:
                        db.execute("UPDATE jobs SET status='completed',progress=1,finished_at=? "
                                   "WHERE id=?", (now(), key))
                if live_sessions:
                    raise HTTPException(409, "Đã có một phiên camera đang chạy.")
            ident = uuid.uuid4().hex
            config = payload.model_copy(update={"source_id": ident, "max_seconds": 0})
            detector = (detector_factory or PersonDetector)(settings, config)
            fire_detector = (fire_factory or FireDetector)(settings) if config.detect_fire else None
            analyzer = LiveAnalyzer(config, detector, fire_detector)
            live_sessions[ident] = {"analyzer": analyzer, "lock": threading.Lock(),
                                    "user_id": current["id"], "last_seen": time.monotonic()}
            with db.connect() as conn:
                conn.execute("INSERT INTO sources VALUES(?,?,?,?,?)",
                             (ident, config.camera_name, str(settings.runtime / "live" / ident),
                              "live", "live"))
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
                _, delivery_status = notifier.send(
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
                db.execute("UPDATE jobs SET status='completed',progress=1,finished_at=? WHERE id=?",
                           (now(), ident))
        db.audit(current["id"], "stop_live", ident)
        return {"ok": True}

    @app.get("/api/jobs")
    def jobs(
        offset: int = Query(0, ge=0), limit: int = Query(30, ge=1, le=100), current=Depends(user)
    ):
        return {
            "items": [
                public_job(x)
                for x in db.all(
                    "SELECT j.*,s.name source_name FROM jobs j JOIN sources s ON j.source_id=s.id ORDER BY created_at DESC,id DESC LIMIT ? OFFSET ?",
                    (limit, offset),
                )
            ],
            "total": db.one("SELECT count(*) n FROM jobs")["n"],
        }

    @app.get("/api/jobs/{ident}")
    def get_job(ident: str, current=Depends(user)):
        return job(ident)

    @app.post("/api/jobs/{ident}/cancel")
    def cancel_job(ident: str, current=Depends(operator)):
        job(ident)
        with db.connect() as conn:
            conn.execute(
                "UPDATE jobs SET status='cancelled',cancel=1,finished_at=? WHERE id=? AND status='queued'",
                (now(), ident),
            )
            conn.execute("UPDATE jobs SET cancel=1 WHERE id=? AND status='running'", (ident,))
        db.audit(current["id"], "cancel_job", ident)
        return job(ident)

    @app.get("/api/jobs/{ident}/files/{name}")
    def artifact(ident: str, name: str, current=Depends(user)):
        row = job(ident)
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

    @app.get("/api/alerts")
    def alerts(
        job_id: str = "",
        status: str = "",
        offset: int = Query(0, ge=0),
        limit: int = Query(50, ge=1, le=100),
        current=Depends(user),
    ):
        where = "WHERE (?='' OR a.job_id=?) AND (?='' OR a.status=?)"
        args = (job_id, job_id, status, status)
        rows = db.all(
            "SELECT a.*,s.name source_name,j.config FROM alerts a JOIN jobs j ON j.id=a.job_id JOIN sources s ON s.id=j.source_id "
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
            "total": db.one("SELECT count(*) n FROM alerts a " + where, args)["n"],
        }

    @app.patch("/api/alerts/{ident}")
    def review_alert(ident: str, payload: AlertUpdate, current=Depends(operator)):
        with db.connect() as conn:
            if not conn.execute("SELECT id FROM alerts WHERE id=?", (ident,)).fetchone():
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
        row = db.one("SELECT job_id,evidence FROM alerts WHERE id=?", (ident,))
        if not row:
            raise HTTPException(404, "Không có cảnh báo.")
        path = settings.runtime / "jobs" / row["job_id"] / row["evidence"]
        if not path.is_file():
            raise HTTPException(404, "Không tìm thấy ảnh bằng chứng.")
        return FileResponse(path, media_type="image/jpeg")

    @app.post("/api/alerts/{ident}/telegram")
    def retry_telegram(ident: str, current=Depends(operator)):
        """Manually resend an unsent alert; never resend a confirmed delivery."""
        if not notifier.configured:
            raise HTTPException(409, "Chưa cấu hình bot token và chat ID Telegram.")
        with telegram_retry_lock:
            row = db.one(
                "SELECT a.*,j.config,j.status job_status FROM alerts a "
                "JOIN jobs j ON j.id=a.job_id WHERE a.id=?", (ident,)
            )
            if not row:
                raise HTTPException(404, "Không có cảnh báo.")
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
            delivered, status = notifier.send(
                alert, path.read_bytes(), config["camera_name"], row["video_time"]
            )
            db.execute("UPDATE alerts SET telegram_status=? WHERE id=?", (status, ident))
            db.audit(current["id"], "retry_telegram", ident, status)
            return {"delivered": delivered, "telegram_status": status}

    @app.get("/api/export/alerts.csv")
    def export(current=Depends(user)):
        rows = db.all(
            "SELECT id,job_id,created_at,video_time,zone,track_id,confidence,dwell,status,note,event_type,severity,details FROM alerts ORDER BY created_at,id"
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

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return Response(status_code=204)

    return app
