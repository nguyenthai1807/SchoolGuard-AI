"""Shared video/webcam inference rules for a single local browser camera."""

import time

import cv2
import numpy as np

from .behavior import BehaviorEngine
from .fire import FireEngine
from .rules import ZoneEngine


class LiveAnalyzer:
    def __init__(self, config, detector, fire_detector=None, clock=time.monotonic):
        self.config = config
        self.detector = detector
        self.fire_detector = fire_detector
        self.clock = clock
        self.started = clock()
        self.last_stamp = -1.0
        self.behavior = None
        self.zones = ZoneEngine(config.zones, config.dwell_seconds, 2.5)
        self.fire = FireEngine(max_gap=2.5)
        self.last_fire = -10.0
        self.frames = 0

    def update(self, jpeg_bytes):
        if not jpeg_bytes or len(jpeg_bytes) > 3 * 1024 * 1024:
            raise ValueError("Ảnh camera vượt giới hạn 3 MB hoặc rỗng.")
        frame = cv2.imdecode(np.frombuffer(jpeg_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            raise ValueError("Không đọc được ảnh JPEG từ camera.")
        height, width = frame.shape[:2]
        if width > 1920 or height > 1080 or width < 160 or height < 120:
            raise ValueError("Camera cần độ phân giải từ 160×120 đến 1920×1080.")
        stamp = max(self.clock() - self.started, self.last_stamp + 0.001)
        self.last_stamp = stamp
        if self.behavior is None:
            self.behavior = BehaviorEngine(self.config, width / height, 2.5)
        detections = self.detector(frame)
        zone_alerts, _ = self.zones.update(detections, stamp)
        alerts = [
            {**a, "event_type": "restricted_zone", "severity": "warning",
             "details": {"reason": "zone_dwell", "experimental": False}}
            for a in zone_alerts
        ]
        alerts.extend(self.behavior.update(detections, stamp))
        hazards = []
        if self.fire_detector and stamp - self.last_fire >= 0.5:
            hazards = self.fire_detector(frame)
            alerts.extend(self.fire.update(hazards, stamp))
            self.last_fire = stamp
        self.frames += 1
        return {"time": stamp, "detections": detections, "hazards": hazards,
                "alerts": alerts, "people": len(detections), "frame": frame}
