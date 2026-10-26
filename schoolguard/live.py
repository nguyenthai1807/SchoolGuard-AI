"""Shared video/webcam inference rules for a single local browser camera."""

import time

import cv2
import numpy as np

from .behavior import BehaviorEngine
from .fire import FireEngine, filter_hazards
from .rules import ZoneEngine
from .tracking import StableIds, merge_body_and_pose
from .weapons import WeaponEngine


class LiveAnalyzer:
    def __init__(self, config, detector, fire_detector=None, clock=time.monotonic,
                 face_ledger=None, object_detector=None, body_detector=None,
                 weapon_detector=None):
        self.config = config
        self.detector = detector
        self.object_detector = object_detector
        self.body_detector = body_detector
        self.weapon_detector = weapon_detector
        self.identities = StableIds()
        self.fire_detector = fire_detector
        self.face_ledger = face_ledger
        self.last_face = -10.0
        self.face_state = {"visible": [], "total": 0, "day": None}
        self.clock = clock
        self.started = clock()
        self.last_stamp = -1.0
        self.behavior = None
        self.zones = ZoneEngine(config.zones, config.dwell_seconds, 2.5)
        self.fire = FireEngine(max_gap=2.5, smoke_dwell=4.0)
        self.last_fire = -10.0
        self.weapon = WeaponEngine()
        self.last_weapon = -10.0
        self.frames = 0

    def reset_view(self):
        """Old screen coordinates cannot be reused after rotation or mirroring."""
        self.identities.records.clear()
        for detector in (self.detector, self.body_detector, self.object_detector):
            if hasattr(detector, "reset_tracking"):
                detector.reset_tracking()
        self.behavior = None
        self.zones = ZoneEngine(self.config.zones, self.config.dwell_seconds, 2.5)
        self.fire = FireEngine(max_gap=2.5, smoke_dwell=4.0)
        self.last_fire = self.last_face = -10.0
        self.weapon = WeaponEngine()
        self.last_weapon = -10.0
        self.face_state["visible"] = []
        if self.face_ledger:
            self.face_ledger.body_faces.clear()
            self.face_ledger.pending_faces.clear()
            for record in self.face_ledger.records.values():
                record["last_bbox"] = record["last_time"] = None

    def update(self, jpeg_bytes):
        if not jpeg_bytes or len(jpeg_bytes) > 3 * 1024 * 1024:
            raise ValueError("Ảnh camera vượt giới hạn 3 MB hoặc rỗng.")
        processing_started = time.perf_counter()
        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Không đọc được ảnh JPEG từ camera.")
        height, width = frame.shape[:2]
        if max(width, height) > 1920 or min(width, height) > 1080 or width < 120 or height < 120:
            raise ValueError("Camera cần độ phân giải từ 160×120 đến 1920×1080.")
        stamp = max(self.clock() - self.started, self.last_stamp + 0.001)
        self.last_stamp = stamp
        if self.behavior is None:
            self.behavior = BehaviorEngine(self.config, width / height, 2.5)
        pose_or_people = self.detector(frame)
        if self.body_detector:
            body_and_objects = self.body_detector(frame)
            body_people = [item for item in body_and_objects if item.get("class_id", 0) == 0]
            other_objects = [item for item in body_and_objects if item.get("class_id", 0) != 0]
            detections = merge_body_and_pose(body_people, pose_or_people) + other_objects
        else:
            detections = pose_or_people
        if self.object_detector:
            detections.extend(self.object_detector(frame))
        detections = self.identities.update(detections, stamp)
        people = [d for d in detections if d.get("class_id", 0) == 0]
        zone_alerts, _ = self.zones.update(people, stamp)
        alerts = [
            {**a, "event_type": "restricted_zone", "severity": "warning",
             "details": {"reason": "zone_dwell", "experimental": False}}
            for a in zone_alerts
        ]
        alerts.extend(self.behavior.update(people, stamp))
        hazards = []
        if self.fire_detector and stamp - self.last_fire >= 0.5:
            hazards = filter_hazards(self.fire_detector(frame), people)
            alerts.extend(self.fire.update(hazards, stamp))
            hazards = self.fire.confirmed
            self.last_fire = stamp
        weapons = []
        if self.weapon_detector and stamp - self.last_weapon >= 0.2:
            candidates = self.weapon_detector(frame, people)
            alerts.extend(self.weapon.update(candidates, stamp))
            weapons = self.weapon.confirmed
            self.last_weapon = stamp
        if self.face_ledger:
            self.face_ledger.observe_people(people, stamp)
        if self.face_ledger and stamp - self.last_face >= 0.35:
            self.face_state = self.face_ledger.update(frame, stamp, people=people)
            self.last_face = stamp
        self.frames += 1
        return {"processing_ms": round((time.perf_counter()-processing_started)*1000), "time": stamp, "detections": detections, "hazards": hazards, "weapons": weapons,
                "alerts": alerts, "people": len(people), "objects": len(detections) - len(people), "frame": frame,
                "faces": self.face_state["visible"] if stamp == self.last_face else [],
                "face_count_today": self.face_state["total"],
                "face_day": self.face_state["day"]}
