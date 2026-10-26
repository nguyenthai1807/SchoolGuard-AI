import json
import logging
import math
import subprocess
import threading
import time
import uuid

import cv2
import imageio_ffmpeg
import numpy as np

from .behavior import BehaviorEngine
from .db import now
from .detector import PersonDetector
from .faces import FaceLedger, FaceRecognizer, draw_faces
from .fire import FireDetector, FireEngine, draw_hazards, filter_hazards
from .media import Reader, jpeg
from .people import PeopleGallery
from .rules import ZoneEngine
from .schemas import POSE_MODELS, JobRequest
from .telegram import TelegramNotifier
from .telegram_link import recipient_for
from .tracking import StableIds, merge_body_and_pose
from .weapons import WeaponDetector, WeaponEngine, draw_weapons

log = logging.getLogger("schoolguard")


def draw(frame, detections, zones, active, redact):
    image = frame.copy()
    h, w = image.shape[:2]
    if redact:
        for d in detections:
            x1, y1, x2, y2 = [int(v * (w if i % 2 == 0 else h)) for i, v in enumerate(d["bbox"])]
            if x2 > x1 and y2 > y1:
                roi = image[y1:y2, x1:x2]
                small = cv2.resize(roi, (max(1, (x2 - x1) // 18), max(1, (y2 - y1) // 18)))
                image[y1:y2, x1:x2] = cv2.resize(
                    small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST
                )
    for i, zone in enumerate(zones):
        points = np.array(
            [[round(x * (w - 1)), round(y * (h - 1))] for x, y in zone.points], dtype=np.int32
        )
        cv2.polylines(image, [points], True, (255, 180, 20), 2)
        cv2.putText(
            image,
            f"ZONE {i + 1}",
            tuple(points[0]),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (255, 180, 20),
            2,
        )
    for d in detections:
        x1, y1, x2, y2 = [int(v * (w if i % 2 == 0 else h)) for i, v in enumerate(d["bbox"])]
        color = (60, 60, 240) if d["track_id"] in active else (80, 210, 70)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        if not redact and d.get("keypoints"):
            pose = d["keypoints"]
            edges = [
                (5, 6),
                (5, 7),
                (7, 9),
                (6, 8),
                (8, 10),
                (5, 11),
                (6, 12),
                (11, 12),
                (11, 13),
                (13, 15),
                (12, 14),
                (14, 16),
            ]
            for a, b in edges:
                if pose[a][2] >= 0.5 and pose[b][2] >= 0.5:
                    cv2.line(
                        image,
                        (int(pose[a][0] * w), int(pose[a][1] * h)),
                        (int(pose[b][0] * w), int(pose[b][1] * h)),
                        (40, 210, 255),
                        2,
                    )
        cv2.circle(image, ((x1 + x2) // 2, min(y2, h - 1)), 3, color, -1)
        label = f"#{d['track_id'] if d['track_id'] is not None else '?'} {d['confidence']:.2f}"
        cv2.putText(
            image,
            label,
            (x1, max(15, y1 - 5)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            color,
            1,
            cv2.LINE_AA,
        )
    return image


class Encoder:
    def __init__(self, directory, width, height, fps):
        self.directory = directory
        self.error_file = (directory / "encoder.log").open("wb")
        self.process = subprocess.Popen(
            [
                imageio_ffmpeg.get_ffmpeg_exe(),
                "-y",
                "-loglevel",
                "error",
                "-f",
                "rawvideo",
                "-vcodec",
                "rawvideo",
                "-pix_fmt",
                "bgr24",
                "-s",
                f"{width}x{height}",
                "-r",
                str(fps),
                "-i",
                "-",
                "-an",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                "23",
                "-vf",
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(directory / "result.partial.mp4"),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=self.error_file,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

    def write(self, frame):
        self.process.stdin.write(frame.tobytes())

    def close(self, publish):
        try:
            self.process.stdin.close()
            result = self.process.wait(timeout=60)
            if publish:
                if result:
                    raise RuntimeError("Mã hóa video thất bại; xem encoder.log.")
                (self.directory / "result.partial.mp4").replace(self.directory / "result.mp4")
        except BaseException:
            if self.process.poll() is None:
                self.process.kill()
                self.process.wait()
            raise
        finally:
            self.error_file.close()


class Cancelled(Exception):
    pass


class Worker:
    def __init__(self, db, settings, detector_factory=PersonDetector, fire_factory=FireDetector,
                 notifier=None, face_factory=FaceRecognizer, weapon_factory=WeaponDetector):
        self.db, self.settings = db, settings
        self.detector_factory = detector_factory
        self.fire_factory = fire_factory
        self.face_factory = face_factory
        self.weapon_factory = weapon_factory
        self.notifier = notifier or TelegramNotifier()
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None
        self.preview_lock = threading.Lock()

    def start(self):
        self.db.execute(
            "UPDATE jobs SET status='failed', error='Server đã khởi động lại khi đang xử lý. Vui lòng chạy lại.',finished_at=? WHERE status='running'",
            (now(),),
        )
        self.thread = threading.Thread(target=self.loop, name="schoolguard-worker", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=60)

    def loop(self):
        while not self.stop.is_set():
            with self.db.connect() as conn:
                row = conn.execute(
                    "SELECT * FROM jobs WHERE status='queued' ORDER BY created_at,id LIMIT 1"
                ).fetchone()
                if row:
                    conn.execute(
                        "UPDATE jobs SET status='running',started_at=? WHERE id=?",
                        (now(), row["id"]),
                    )
            if row:
                self.run(dict(row))
            else:
                self.wake.wait(1)
                self.wake.clear()

    def run(self, job):
        ident = job["id"]
        directory = self.settings.runtime / "jobs" / ident
        directory.mkdir(parents=True, exist_ok=True)
        config = JobRequest.model_validate_json(job["config"])
        source = self.db.one("SELECT * FROM sources WHERE id=?", (job["source_id"],))
        started = time.perf_counter()
        encoder = None
        processed = events = peak = 0
        preview_failures = 0
        inference_ms = []
        try:
            (directory / "config.json").write_text(
                config.model_dump_json(indent=2), encoding="utf-8"
            )
            with Reader(source["path"], source["kind"], config.sequence_fps) as reader:
                total = (
                    min(reader.count, math.ceil(config.max_seconds * reader.fps))
                    if config.max_seconds
                    else reader.count
                )
                self.db.execute("UPDATE jobs SET total_frames=? WHERE id=?", (total, ident))
                detector = self.detector_factory(self.settings, config)
                body_detector = None
                if config.model in POSE_MODELS and self.detector_factory is PersonDetector:
                    body_model = ("yolov8n" if config.model.startswith("yolov8") else
                                  "yolo26s" if config.model.startswith("yolo26") and (self.settings.models / "yolo26s.pt").is_file() else "yolo11s")
                    body_config = config.model_copy(update={"model": body_model})
                    body_detector = PersonDetector(self.settings, body_config, classes=[0])
                fire_detector = self.fire_factory(self.settings) if config.detect_fire else None
                weapon_detector = None  # Retired feature, including previously queued jobs.
                face_ledger = (FaceLedger(self.db, self.settings.runtime, "video", ident,
                                          self.face_factory(self.settings))
                               if config.recognize_faces else None)
                people_gallery = PeopleGallery(directory) if not config.redact else None
                identities = StableIds()
                last_face_time = -10.0
                fire_engine = FireEngine(smoke_dwell=4.0)
                fire_ms = []
                pose_inferred_frames = 0
                last_fire_time = -10.0
                hazards = []
                weapons = []
                weapon_engine = WeaponEngine()
                weapon_ms = []
                last_weapon_time = -10.0
                engine = ZoneEngine(
                    config.zones, config.dwell_seconds, max(0.5, config.stride / reader.fps * 1.5)
                )
                behavior = BehaviorEngine(
                    config, reader.width / reader.height, max(0.5, config.stride / reader.fps * 1.5)
                )
                output_scale = min(1.0, 1280 / reader.width, 720 / reader.height)
                output_size = (max(2, round(reader.width * output_scale)),
                               max(2, round(reader.height * output_scale)))
                encoder = Encoder(directory, *output_size, reader.fps)
                last_write = 0
                detections, people, active = [], [], set()
                with (directory / "detections.jsonl").open("w", encoding="utf-8") as output:
                    for index in range(total):
                        if (
                            self.stop.is_set()
                            or self.db.one("SELECT cancel FROM jobs WHERE id=?", (ident,))["cancel"]
                        ):
                            raise Cancelled()
                        frame = reader.read()
                        if frame is None:
                            raise ValueError("Video kết thúc sớm hơn số frame khai báo.")
                        stamp = index / reader.fps
                        new_alerts = []
                        fire_sampled = False
                        weapon_sampled = False
                        face_result = {"visible": [], "total": 0}
                        if index % config.stride == 0:
                            t = time.perf_counter()
                            pose_sampled = body_detector is None or index % (config.stride * 2) == 0
                            if body_detector:
                                body_people = body_detector(frame)
                                pose_people = detector(frame) if pose_sampled else []
                                pose_inferred_frames += int(pose_sampled)
                                raw_detections = merge_body_and_pose(body_people, pose_people)
                            else:
                                raw_detections = detector(frame)
                                pose_inferred_frames += int(config.model in POSE_MODELS)
                            detections = identities.update(raw_detections, stamp)
                            people = [d for d in detections if d.get('class_id', 0) == 0]
                            if people_gallery:
                                people_gallery.update(frame, people, stamp)
                            inference_ms.append((time.perf_counter() - t) * 1000)
                            new_alerts, active = engine.update(people, stamp)
                            if pose_sampled:
                                new_alerts.extend(behavior.update(people, stamp))
                            if fire_detector and stamp - last_fire_time >= 0.5 - 1e-9:
                                fire_start = time.perf_counter()
                                hazards = filter_hazards(fire_detector(frame), people)
                                fire_ms.append((time.perf_counter() - fire_start) * 1000)
                                new_alerts.extend(fire_engine.update(hazards, stamp))
                                hazards = fire_engine.confirmed
                                last_fire_time = stamp
                                fire_sampled = True
                            if weapon_detector and stamp - last_weapon_time >= 0.2 - 1e-9:
                                weapon_start = time.perf_counter()
                                candidates = weapon_detector(frame, people)
                                weapon_ms.append((time.perf_counter() - weapon_start) * 1000)
                                new_alerts.extend(weapon_engine.update(candidates, stamp))
                                weapons = weapon_engine.confirmed
                                last_weapon_time = stamp
                                weapon_sampled = True
                            active.update(a["track_id"] for a in new_alerts)
                            peak = max(peak, len(people))
                            if face_ledger:
                                face_ledger.observe_people(people, stamp)
                                if stamp - last_face_time >= 0.35 - 1e-9:
                                    face_result = face_ledger.update(frame, stamp, people=people)
                                    last_face_time = stamp
                            output.write(
                                json.dumps(
                                    {
                                        "frame": index,
                                        "time": stamp,
                                        "detections": detections,
                                        "people": len(people),
                                        "hazards": hazards if fire_sampled else [],
                                        "fire_sampled": fire_sampled,
                                        "weapons": weapons if weapon_sampled else [],
                                        "weapon_sampled": weapon_sampled,
                                    },
                                    ensure_ascii=False,
                                )
                                + "\n"
                            )
                        # Skipped frames do not display stale boxes or claim fresh detections.
                        shown = detections if index % config.stride == 0 else []
                        output_frame = (cv2.resize(frame, output_size, interpolation=cv2.INTER_AREA)
                                        if output_scale < 1 else frame)
                        annotated = draw(output_frame, shown, config.zones, active, config.redact)
                        if face_result["visible"]:
                            draw_faces(annotated, face_result["visible"])
                        if fire_sampled:
                            draw_hazards(annotated, hazards)
                        if weapon_sampled:
                            draw_weapons(annotated, weapons)
                        if config.redact and not shown and index % config.stride:
                            # Whole frame blur prevents unredacted skipped frames in exported video.
                            annotated = cv2.GaussianBlur(annotated, (51, 51), 0)
                        cv2.putText(
                            annotated,
                            f"{stamp:.2f}s | persons {len(people) if index % config.stride == 0 else '--'} | {'inferred' if index % config.stride == 0 else 'skipped'}",
                            (10, 23),
                            cv2.FONT_HERSHEY_SIMPLEX,
                            0.5,
                            (255, 255, 255),
                            2,
                        )
                        encoder.write(annotated)
                        for alert in new_alerts:
                            alert_id = uuid.uuid4().hex
                            evidence = alert_id + ".jpg"
                            evidence_bytes = jpeg(annotated)
                            (directory / evidence).write_bytes(evidence_bytes)
                            self.db.execute(
                                "INSERT INTO alerts(id,job_id,created_at,video_time,zone,track_id,confidence,bbox,dwell,evidence,event_type,severity,details) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (
                                    alert_id,
                                    ident,
                                    now(),
                                    stamp,
                                    alert["zone"],
                                    alert["track_id"],
                                    alert["confidence"],
                                    json.dumps(alert["bbox"]),
                                    alert["dwell"],
                                    evidence,
                                    alert.get("event_type", "restricted_zone"),
                                    alert.get("severity", "warning"),
                                    json.dumps(alert.get("details", {}), ensure_ascii=False),
                                ),
                            )
                            events += 1
                            _, delivery_status = recipient_for(self.db, job["user_id"], self.notifier).send(
                                alert, evidence_bytes, config.camera_name, stamp
                            )
                            self.db.execute(
                                "UPDATE alerts SET telegram_status=? WHERE id=?",
                                (delivery_status, alert_id),
                            )
                        processed += 1
                        if time.perf_counter() - last_write >= 0.5 or processed == total:
                            # Windows prevents replacing a file held by FileResponse/AV.
                            # A missed preview must never abort inference or the result video.
                            with self.preview_lock:
                                temp = directory / "preview.tmp"
                                temp.write_bytes(jpeg(annotated))
                                try:
                                    temp.replace(directory / "preview.jpg")
                                except PermissionError:
                                    preview_failures += 1
                            elapsed = time.perf_counter() - started
                            self.db.execute(
                                "UPDATE jobs SET progress=?,frames=?,people=?,events=?,fps=? WHERE id=?",
                                (
                                    processed / total,
                                    processed,
                                    len(people),
                                    events,
                                    processed / elapsed,
                                    ident,
                                ),
                            )
                            last_write = time.perf_counter()
                    output.flush()
                encoder.close(True)
                encoder = None
                elapsed = time.perf_counter() - started
                gallery_result = people_gallery.finish() if people_gallery else None
                summary = {
                    "processed_frames": processed,
                    "inferred_frames": len(inference_ms),
                    "source_frames": reader.count,
                    "source_fps": reader.fps,
                    "fps_assumed": source["kind"] == "frames",
                    "source_duration": reader.count / reader.fps,
                    "processed_duration": processed / reader.fps,
                    "partial_clip": processed < reader.count,
                    "peak_people": peak,
                    "last_observed_people": len(people),
                    "output_size": list(output_size),
                    "alerts": events,
                    "elapsed_seconds": round(elapsed, 3),
                    "processing_fps": round(processed / elapsed, 2),
                    "inference_mean_ms": round(float(np.mean(inference_ms)), 2),
                    "inference_p95_ms": round(float(np.percentile(inference_ms, 95)), 2),
                    "device": getattr(detector, "device", "test"),
                    "redacted": config.redact,
                    "model": config.model,
                    "checkpoint_sha256": getattr(detector, "checkpoint_sha256", None),
                    "body_checkpoint_sha256": getattr(body_detector, "checkpoint_sha256", None),
                    "pose_inferred_frames": pose_inferred_frames,
                    "schema_version": "2.0",
                    "event_counts": {
                        row["event_type"]: row["n"]
                        for row in self.db.all(
                            "SELECT event_type,count(*) n FROM alerts WHERE job_id=? GROUP BY event_type",
                            (ident,),
                        )
                    },
                    "behavior_rules": "lh25-home-v1-experimental",
                    "fire_checkpoint_sha256": getattr(fire_detector, "checkpoint_sha256", None),
                    "weapon_checkpoint_sha256": getattr(weapon_detector, "checkpoint_sha256", None),
                    "fire_inferred_frames": len(fire_ms),
                    "weapon_inferred_frames": len(weapon_ms),
                    "unique_faces": len(face_ledger.records) if face_ledger else None,
                    "tracked_people": gallery_result["count"] if gallery_result else None,
                    "people_gallery_truncated": gallery_result["truncated"] if gallery_result else False,
                    "preview_write_retries": preview_failures,
                    "fire_mean_ms": round(float(np.mean(fire_ms)), 2) if fire_ms else None,
                    "weapon_mean_ms": round(float(np.mean(weapon_ms)), 2) if weapon_ms else None,
                }
                (directory / "summary.json").write_text(
                    json.dumps(summary, indent=2), encoding="utf-8"
                )
                self.db.execute(
                    "UPDATE jobs SET status='completed',progress=1,finished_at=?,summary=? WHERE id=?",
                    (now(), json.dumps(summary), ident),
                )
                log.info(
                    "Completed %s: %s frames, %s events, %.2f FPS",
                    ident,
                    processed,
                    events,
                    processed / elapsed,
                )
        except Cancelled:
            self.db.execute(
                "UPDATE jobs SET status='cancelled',finished_at=? WHERE id=?", (now(), ident)
            )
        except Exception as exc:
            log.exception("Job %s failed", ident)
            self.db.execute(
                "UPDATE jobs SET status='failed',finished_at=?,error=? WHERE id=?",
                (now(), str(exc)[:1000], ident),
            )
        finally:
            if encoder:
                try:
                    encoder.close(False)
                except Exception:
                    log.exception("Encoder cleanup failed")
