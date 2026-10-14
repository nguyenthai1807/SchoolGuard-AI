"""Validated, normalized data contracts shared by the worker and backend."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

Point = tuple[float, float]
Box = tuple[float, float, float, float]


def nonnegative(value: float, name: str) -> None:
    if not math.isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and >= 0")


def cross(a: Point, b: Point, c: Point) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a: Point, b: Point, p: Point) -> bool:
    return abs(cross(a, b, p)) < 1e-9 and all(
        min(a[i], b[i]) - 1e-9 <= p[i] <= max(a[i], b[i]) + 1e-9 for i in (0, 1)
    )


def intersects(a: Point, b: Point, c: Point, d: Point) -> bool:
    return (cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0) or any(
        (on_segment(a, b, c), on_segment(a, b, d), on_segment(c, d, a), on_segment(c, d, b))
    )


@dataclass(frozen=True)
class Zone:
    zone_id: str
    name: str
    polygon: tuple[Point, ...]

    def __post_init__(self) -> None:
        if not self.zone_id or not self.name:
            raise ValueError("zone_id and name are required")
        p = self.polygon
        if len(p) < 3 or len(set(p)) != len(p):
            raise ValueError("polygon needs at least three distinct vertices; do not repeat first")
        if any(len(v) != 2 or any(not math.isfinite(x) or not 0 <= x <= 1 for x in v) for v in p):
            raise ValueError("polygon coordinates must be finite normalized [0, 1] pairs")
        n = len(p)
        area = sum(p[i][0] * p[(i + 1) % n][1] - p[(i + 1) % n][0] * p[i][1] for i in range(n))
        if abs(area) < 1e-9:
            raise ValueError("polygon area must be non-zero")
        for i in range(n):
            for j in range(i + 1, n):
                if j == i + 1 or (i == 0 and j == n - 1):
                    continue
                if intersects(p[i], p[(i + 1) % n], p[j], p[(j + 1) % n]):
                    raise ValueError("polygon edges must not intersect")


@dataclass(frozen=True)
class Detection:
    track_id: int | None
    confidence: float
    bbox: Box
    label: str = "person"

    def __post_init__(self) -> None:
        if self.track_id is not None and (type(self.track_id) is not int or self.track_id < 0):
            raise ValueError("track_id must be a nonnegative integer or None")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("confidence must be in [0, 1]")
        if len(self.bbox) != 4 or any(not math.isfinite(x) or not 0 <= x <= 1 for x in self.bbox):
            raise ValueError("bbox must be four finite normalized coordinates")
        x1, y1, x2, y2 = self.bbox
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must have positive width and height")


@dataclass(frozen=True)
class Config:
    camera_id: str
    zones: tuple[Zone, ...]
    model: str = "yolov8n.pt"
    confidence: float = 0.35
    image_size: int = 640
    frame_stride: int = 1
    device: str = "cpu"
    anchor: Literal["center", "bottom"] = "center"
    dwell_seconds: float = 2.0
    missing_grace_seconds: float = 0.5
    redact_people: bool = True

    def __post_init__(self) -> None:
        if not self.camera_id or not self.model or not self.device:
            raise ValueError("camera_id, model and device are required")
        if not self.zones or len({z.zone_id for z in self.zones}) != len(self.zones):
            raise ValueError("at least one zone with unique zone_id is required")
        if self.anchor not in ("center", "bottom"):
            raise ValueError("anchor must be center or bottom")
        if not math.isfinite(self.confidence) or not 0 < self.confidence <= 1:
            raise ValueError("confidence must be in (0, 1]")
        for key in ("frame_stride", "image_size"):
            value = getattr(self, key)
            if type(value) is not int or value < 1:
                raise ValueError(f"{key} must be a positive integer")
        if type(self.redact_people) is not bool:
            raise ValueError("redact_people must be a boolean")
        nonnegative(self.dwell_seconds, "dwell_seconds")
        nonnegative(self.missing_grace_seconds, "missing_grace_seconds")

    @classmethod
    def load(cls, path: Path) -> Config:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        data["zones"] = tuple(
            Zone(z["zone_id"], z["name"], tuple(tuple(v) for v in z["polygon"]))
            for z in data["zones"]
        )
        return cls(**data)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class Intrusion:
    zone_id: str
    detection: Detection
    video_time_seconds: float
    dwell_seconds: float


@dataclass
class RuleResult:
    intrusions: list[Intrusion] = field(default_factory=list)
    # Detection indexes, not IDs: untracked detections still contribute to occupancy.
    zone_members: dict[str, list[int]] = field(default_factory=dict)
    alerting_tracks: set[tuple[str, int]] = field(default_factory=set)
