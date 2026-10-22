from __future__ import annotations

from pathlib import Path

import pytest

from home_video_analysis import (
    analyze_person_video,
    can_use_person_worker,
    rectangles_to_config,
    validate_video_duration,
)

PERSON_ZONE = {
    "id": "front-door",
    "name": "Cửa chính",
    "x": 0.1,
    "y": 0.2,
    "width": 0.3,
    "height": 0.4,
    "classes": [0],
}


def test_only_person_zones_are_routed_to_the_be1_worker():
    assert can_use_person_worker([PERSON_ZONE]) is True
    assert can_use_person_worker([{**PERSON_ZONE, "classes": [0, 2]}]) is False
    assert can_use_person_worker([{**PERSON_ZONE, "classes": [2]}]) is False
    assert can_use_person_worker([]) is False


def test_rectangles_are_converted_to_normalized_polygons():
    config = rectangles_to_config(
        [PERSON_ZONE],
        source_id="front-door-test.mp4",
        model="local-model.pt",
        dwell_seconds=3.5,
    )

    assert config.camera_id == "front-door-test.mp4"
    assert config.model == "local-model.pt"
    assert config.dwell_seconds == 3.5
    assert config.zones[0].zone_id == "front-door"
    assert config.zones[0].name == "Cửa chính"
    assert config.zones[0].polygon == (
        (0.1, 0.2),
        (0.4, 0.2),
        (0.4, pytest.approx(0.6)),
        (0.1, pytest.approx(0.6)),
    )


def test_worker_output_is_normalized_for_the_existing_frontend(tmp_path, monkeypatch):
    run_dir = tmp_path / "run-123"
    snapshot = run_dir / "snapshots" / "event-1.jpg"
    annotated = run_dir / "annotated.mp4"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(b"jpeg")
    annotated.write_bytes(b"video")

    def fake_process_video(
        source,
        config,
        output_root,
        event_sink,
        save_video,
        max_input_frames,
    ):
        assert source == tmp_path / "input.mp4"
        assert output_root == tmp_path / "runs"
        assert save_video is True
        assert max_input_frames == 10_800
        event_sink(
            {
                "event_id": "event-1",
                "run_id": "run-123",
                "zone_id": "front-door",
                "track_id": 9,
                "confidence": 0.91,
                "video_time_seconds": 4.25,
                "evidence": {"path": "snapshots/event-1.jpg"},
            }
        )
        return {
            "run_id": "run-123",
            "output_dir": str(run_dir),
            "annotated_video": "annotated.mp4",
            "last_video_time_seconds": 8.5,
            "processed_frames": 34,
            "peak_people": 2,
            "event_count": 1,
            "browser_playable": True,
        }

    monkeypatch.setattr("home_video_analysis.process_video", fake_process_video)

    result = analyze_person_video(
        tmp_path / "input.mp4",
        tmp_path / "runs",
        [PERSON_ZONE],
        source_id="front-door-test.mp4",
    )

    assert result["duration_seconds"] == 8.5
    assert result["processed_frames"] == 34
    assert result["people_count"] == 2
    assert result["vehicle_counts"] == {}
    assert result["uniform_groups"] == []
    assert result["engine"] == "be1-yolo-bytetrack"
    assert result["output_path"] == annotated
    assert result["events"] == [
        {
            "zone_id": "front-door",
            "zone_name": "Cửa chính",
            "object_type": "person",
            "track_id": 9,
            "confidence": 0.91,
            "media_offset_seconds": 4.25,
            "image_path": snapshot,
        }
    ]


def test_video_duration_limit_is_enforced_before_analysis(monkeypatch):
    class FakeCapture:
        def isOpened(self):
            return True

        def get(self, key):
            return {3: 1280.0, 4: 720.0, 5: 30.0, 7: 5_401}[key]

        def release(self):
            pass

    monkeypatch.setattr("home_video_analysis.cv2.VideoCapture", lambda _: FakeCapture())

    with pytest.raises(ValueError, match="3 phút"):
        validate_video_duration(Path("too-long.mp4"), max_seconds=180)


def test_video_above_60_fps_is_rejected_before_worker(monkeypatch):
    class FakeCapture:
        def isOpened(self):
            return True

        def get(self, key):
            return {3: 1280.0, 4: 720.0, 5: 120.0, 7: 10_800}[key]

        def release(self):
            pass

    monkeypatch.setattr("home_video_analysis.cv2.VideoCapture", lambda _: FakeCapture())

    with pytest.raises(ValueError, match="60 FPS"):
        validate_video_duration(Path("high-fps.mp4"))
