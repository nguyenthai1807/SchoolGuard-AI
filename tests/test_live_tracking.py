from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np
import pytest

import video_analysis


def test_live_zone_anchor_matches_batch_worker(monkeypatch):
    box = (0.2, 0.2, 0.4, 0.8)
    zone = {"x": 0.1, "y": 0.7, "width": 0.5, "height": 0.2}

    monkeypatch.setenv("ZONE_ANCHOR", "bottom")
    assert video_analysis._inside_zone(box, zone) is True

    monkeypatch.setenv("ZONE_ANCHOR", "center")
    assert video_analysis._inside_zone(box, zone) is False


def test_live_tracker_models_are_isolated_and_bounded_by_stream(monkeypatch):
    created = []

    class FakeYolo:
        def __init__(self, model):
            self.model = model
            created.append(self)

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeYolo))
    monkeypatch.setattr(video_analysis, "MAX_LIVE_STREAMS", 2)
    video_analysis._live_models.clear()
    video_analysis._live_model_seen.clear()

    first = video_analysis._get_live_model("webcam")
    second = video_analysis._get_live_model("video")
    assert first is not second
    assert video_analysis._get_live_model("webcam") is first

    video_analysis._get_live_model("another-webcam")
    assert len(video_analysis._live_models) == 2
    assert len(created) == 3


def test_uploaded_video_analyses_receive_fresh_trackers(monkeypatch):
    created = []

    class FakeYolo:
        def __init__(self, model):
            self.model = model
            created.append(self)

    monkeypatch.setitem(sys.modules, "ultralytics", SimpleNamespace(YOLO=FakeYolo))

    first = video_analysis._get_model()
    second = video_analysis._get_model()

    assert first is not second
    assert len(created) == 2


def test_release_live_stream_clears_tracker_and_presence():
    video_analysis._live_models["stopped"] = object()
    video_analysis._live_model_seen["stopped"] = 1.0
    video_analysis._live_presence[("stopped", "zone-1", 7, 0)] = {
        "started": 1.0,
        "last_seen": 2.0,
    }

    assert video_analysis.release_live_stream("stopped") is True
    assert "stopped" not in video_analysis._live_models
    assert not any(key[0] == "stopped" for key in video_analysis._live_presence)


def test_live_dwell_resets_after_long_gap(monkeypatch):
    class Tensor:
        def __init__(self, values):
            self.values = np.asarray(values)

        def cpu(self):
            return self

        def numpy(self):
            return self.values

        def int(self):
            return Tensor(self.values.astype(int))

        def tolist(self):
            return self.values.tolist()

    boxes = SimpleNamespace(
        xyxy=Tensor([[10, 10, 30, 40]]),
        cls=Tensor([0]),
        conf=Tensor([0.9]),
        id=Tensor([7]),
    )
    model = SimpleNamespace(track=lambda *_args, **_kwargs: [SimpleNamespace(boxes=boxes)])
    monkeypatch.setattr(video_analysis, "_get_live_model", lambda _stream_id: model)
    monkeypatch.setattr(video_analysis, "_validate_encoded_image_dimensions", lambda _bytes: None)
    monkeypatch.setattr(
        video_analysis.cv2,
        "imdecode",
        lambda *_args, **_kwargs: np.zeros((100, 100, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(video_analysis, "monotonic", lambda: 10.0)
    monkeypatch.setenv("ZONE_DWELL_SECONDS", "5")
    monkeypatch.setenv("TRACK_MISSING_GRACE_SECONDS", "0.5")
    video_analysis._live_presence.clear()
    key = ("webcam", "zone-1", 7, 0)
    video_analysis._live_presence[key] = {
        "started": 0.0,
        "last_seen": 1.0,
        "triggered": False,
    }

    result = video_analysis.detect_live_frame_jpeg(
        b"jpeg",
        zones=[
            {
                "id": "zone-1",
                "name": "Cửa chính",
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "classes": [0],
            }
        ],
        stream_id="webcam",
        selected_classes=[0],
    )

    assert result["events"] == []
    assert video_analysis._live_presence[key]["started"] == 10.0


def test_live_reidentification_does_not_reuse_one_track_twice(monkeypatch):
    class Tensor:
        def __init__(self, values):
            self.values = np.asarray(values)

        def cpu(self):
            return self

        def numpy(self):
            return self.values

        def int(self):
            return Tensor(self.values.astype(int))

        def tolist(self):
            return self.values.tolist()

    boxes = SimpleNamespace(
        xyxy=Tensor([[10, 10, 30, 40], [12, 10, 32, 40]]),
        cls=Tensor([0, 0]),
        conf=Tensor([0.9, 0.9]),
        id=Tensor([8, 9]),
    )
    model = SimpleNamespace(track=lambda *_args, **_kwargs: [SimpleNamespace(boxes=boxes)])
    monkeypatch.setattr(video_analysis, "_get_live_model", lambda _stream_id: model)
    monkeypatch.setattr(video_analysis, "_validate_encoded_image_dimensions", lambda _bytes: None)
    monkeypatch.setattr(
        video_analysis.cv2,
        "imdecode",
        lambda *_args, **_kwargs: np.zeros((100, 100, 3), dtype=np.uint8),
    )
    monkeypatch.setattr(video_analysis, "monotonic", lambda: 10.0)
    monkeypatch.setenv("ZONE_DWELL_SECONDS", "5")
    monkeypatch.setenv("TRACK_MISSING_GRACE_SECONDS", "1")
    video_analysis._live_presence.clear()
    video_analysis._live_models["webcam"] = object()
    video_analysis._live_model_seen["webcam"] = 10.0
    old_key = ("webcam", "zone-1", 7, 0)
    video_analysis._live_presence[old_key] = {
        "started": 0.0,
        "last_seen": 9.5,
        "center": (0.2, 0.25),
        "triggered": False,
    }

    result = video_analysis.detect_live_frame_jpeg(
        b"jpeg",
        zones=[
            {
                "id": "zone-1",
                "name": "Cửa chính",
                "x": 0.0,
                "y": 0.0,
                "width": 1.0,
                "height": 1.0,
                "classes": [0],
            }
        ],
        stream_id="webcam",
        selected_classes=[0],
    )

    assert len(result["events"]) == 1
    assert video_analysis._live_presence[("webcam", "zone-1", 8, 0)]["started"] == 0.0
    assert video_analysis._live_presence[("webcam", "zone-1", 9, 0)]["started"] == 10.0


def test_live_frame_dimensions_are_rejected_before_opencv_decode(monkeypatch):
    class OversizedImage:
        size = (3840, 2160)

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(video_analysis.Image, "open", lambda *_args, **_kwargs: OversizedImage())
    monkeypatch.setattr(
        video_analysis.cv2,
        "imdecode",
        lambda *_args, **_kwargs: pytest.fail("OpenCV must not decode an oversized frame"),
    )

    with pytest.raises(ValueError, match="Full HD"):
        video_analysis.detect_live_frame_jpeg(b"encoded-image")
