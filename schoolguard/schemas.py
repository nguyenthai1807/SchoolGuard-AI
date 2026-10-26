import math
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DemoPick(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str = Field(min_length=1, max_length=64)
    capability: Literal["fall", "fire", "people", "face", "interaction"]
    evidence_job_id: str = Field(min_length=1, max_length=64)
    rights_note: str = Field(min_length=8, max_length=300)
    review_note: str = Field(min_length=15, max_length=500)
    review_confirmed: bool
    academic_only: bool = False


def cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def on_segment(a, b, p):
    return (
        abs(cross(a, b, p)) < 1e-9
        and min(a[0], b[0]) - 1e-9 <= p[0] <= max(a[0], b[0]) + 1e-9
        and min(a[1], b[1]) - 1e-9 <= p[1] <= max(a[1], b[1]) + 1e-9
    )


def inside(point, polygon):
    result = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if on_segment(a, b, point):
            return True
        if (a[1] > point[1]) != (b[1] > point[1]):
            if point[0] < (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]:
                result = not result
    return result


class Zone(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(default="Vùng hạn chế", min_length=1, max_length=80)
    points: list[tuple[float, float]] = Field(min_length=3, max_length=30)

    @model_validator(mode="after")
    def valid_polygon(self):
        p = self.points
        if any(not math.isfinite(v) or not 0 <= v <= 1 for xy in p for v in xy):
            raise ValueError("Điểm vùng phải nằm trong ảnh (0–1).")
        if len(set(p)) != len(p):
            raise ValueError("Các điểm không được trùng nhau.")
        area = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(p, p[1:] + p[:1]))
        if abs(area) < 0.00001:
            raise ValueError("Vùng phải có diện tích.")
        edges = list(zip(p, p[1:] + p[:1]))
        for i, (a, b) in enumerate(edges):
            for j, (c, d) in enumerate(edges):
                if j <= i or j == i + 1 or (i == 0 and j == len(p) - 1):
                    continue
                if (
                    cross(a, b, c) * cross(a, b, d) < 0 and cross(c, d, a) * cross(c, d, b) < 0
                ) or any(
                    (
                        on_segment(a, b, c),
                        on_segment(a, b, d),
                        on_segment(c, d, a),
                        on_segment(c, d, b),
                    )
                ):
                    raise ValueError("Các cạnh vùng không được tự cắt nhau.")
        return self


POSE_MODELS = frozenset({"yolov8n-pose", "yolo11n-pose", "yolo26n-pose"})
COCO_DETECTION_MODELS = frozenset({"yolov8n", "yolov9t", "yolov10n", "yolo11n", "yolo11s",
                                   "yolo12n", "yolo26n", "yolo26s"})
EFFORT_PRESETS = {
    "low": (640, 5), "medium": (640, 3), "high": (640, 1),
    "extra": (960, 2), "extra_max": (960, 1),
}


class JobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    source_id: str
    camera_name: str = Field(default="Camera thử nghiệm", min_length=1, max_length=80)
    zones: list[Zone] = Field(default_factory=list, max_length=8)
    model: Literal["yolov8n", "yolov8n-pose", "yolov9t", "yolov10n",
                   "yolo11n", "yolo11s", "schoolguard-person-v1", "yolo11n-pose",
                   "yolo12n", "yolo26n", "yolo26s", "yolo26n-pose"] = "yolov8n"
    image_size: Literal[640, 960] = 640
    confidence: float = Field(default=0.35, ge=0.1, le=0.95)
    dwell_seconds: float = Field(default=1.5, ge=0, le=60)
    stride: int = Field(default=1, ge=1, le=5, strict=True)
    effort: Literal["low", "medium", "high", "extra", "extra_max"] | None = None
    max_seconds: float = Field(default=30, ge=0, le=3600)
    sequence_fps: float = Field(default=25, ge=1, le=120)
    redact: bool = False
    detect_falls: bool = False
    detect_interactions: bool = False
    detect_fire: bool = False
    detect_weapons: bool = False
    recognize_faces: bool = False
    detect_objects: bool = False
    camera_rotation: Literal[0, 90, 180, 270] = 0
    camera_mirror: bool = False
    camera_url: str = Field(default="", max_length=2048, exclude=True)
    camera_username: str = Field(default="", max_length=256, exclude=True)
    camera_password: str = Field(default="", max_length=256, exclude=True)
    lying_seconds: float = Field(default=8, ge=2, le=120)
    crowd_threshold: int = Field(default=0, ge=0, le=200, strict=True)
    crowd_seconds: float = Field(default=3, ge=1, le=60)
    expected_people: int | None = Field(default=None, ge=0, le=20, strict=True)
    loiter_seconds: float = Field(default=0, ge=0, le=3600)

    @model_validator(mode="after")
    def require_pose(self):
        if self.effort:
            image_size, stride = EFFORT_PRESETS[self.effort]
            if ("image_size" in self.model_fields_set and self.image_size != image_size) or (
                    "stride" in self.model_fields_set and self.stride != stride):
                raise ValueError("Cấu hình độ phân giải/frame không khớp mức Effort đã chọn.")
            self.image_size, self.stride = image_size, stride
        if (self.detect_falls or self.detect_interactions) and self.model not in POSE_MODELS:
            raise ValueError("Cảnh báo tư thế cần model -pose (YOLO8, YOLO11 hoặc YOLO26).")
        if self.recognize_faces and self.redact:
            raise ValueError("Không thể vừa che mờ người vừa lưu ảnh khuôn mặt.")
        return self


class CameraView(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation: Literal[0, 90, 180, 270] = 0
    mirror: bool = False


class Login(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=200)


class UserCreate(Login):
    role: Literal["admin", "operator", "viewer"] = "viewer"
    password: str = Field(min_length=12, max_length=200)


class PublicRegistration(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    username: str = Field(min_length=3, max_length=50, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=12, max_length=200)
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254,
                       pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    consent: Literal[True]


class PaymentConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    payment_reference: str = Field(min_length=4, max_length=120)


class ManualPaymentLink(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    url: str = Field(min_length=20, max_length=512)


class VerifyEmailToken(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=32, max_length=200, pattern=r"^[A-Za-z0-9_-]+$")


class CustomerProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    display_name: str = Field(min_length=2, max_length=100)
    email: str = Field(min_length=3, max_length=254,
                       pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    phone: str = Field(default="", max_length=25,
                       pattern=r"^$|^\+?[0-9 .()-]{7,25}$")


class AlertUpdate(BaseModel):
    status: Literal["new", "acknowledged", "resolved", "false_positive"]
    note: str = Field(default="", max_length=1000)
