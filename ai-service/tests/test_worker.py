"""Exercise real video IO and evidence exports with deterministic injected detections."""

import json
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import pytest

from schoolguard_ai.models import Config, Detection, Zone
from schoolguard_ai.worker import process_video


def make_video(path: Path, frames: int = 40) -> None:
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 10, (320, 240))
    assert writer.isOpened()
    for index in range(frames):
        frame = np.zeros((240, 320, 3), dtype=np.uint8)
        cv2.rectangle(frame, (190, 40), (240, 200), (255, 255, 255), -1)
        cv2.putText(frame, str(index), (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0))
        writer.write(frame)
    writer.release()


class FixedDetector:
    def detect(self, frame):
        return [Detection(7, 0.9, (0.59, 0.16, 0.75, 0.84))]


def config():
    return Config("CAM-01", (Zone("ZONE-01", "Restricted", ((0.5, 0), (1, 0), (1, 1), (0.5, 1))),))


def test_pipeline_contract_evidence_and_stride(tmp_path):
    video = tmp_path / "input.mp4"
    make_video(video)
    delivered = []
    summary = process_video(
        video,
        replace(config(), frame_stride=2),
        tmp_path / "out",
        detector=FixedDetector(),
        event_sink=delivered.append,
    )
    out = Path(summary["output_dir"])
    events = [json.loads(line) for line in (out / "events.jsonl").read_text().splitlines()]
    frames = [json.loads(line) for line in (out / "frames.jsonl").read_text().splitlines()]
    assert summary["processed_frames"] == 20
    assert summary["event_count"] == 1
    assert events == delivered
    assert events[0]["video_time_seconds"] == 2.0
    assert events[0]["frame_index"] == 20
    assert events[0]["track_id"] == 7
    assert events[0]["evidence"]["redacted"] is True
    assert events[0]["bbox"] == [0.59, 0.16, 0.75, 0.84]
    assert events[0]["detected_at"].endswith("Z")
    assert cv2.imread(str(out / events[0]["evidence"]["path"])) is not None
    assert frames[-1]["zone_counts"] == {"ZONE-01": 1}
    assert frames[-1]["detections"][0]["alerting"] is True
    cap = cv2.VideoCapture(str(out / summary["annotated_video"]))
    assert cap.isOpened() and int(cap.get(cv2.CAP_PROP_FRAME_COUNT)) == 20
    cap.release()


def test_failed_callback_leaves_event_for_replay(tmp_path):
    video = tmp_path / "input.mp4"
    make_video(video)

    def unavailable(event):
        raise RuntimeError("backend offline")

    with pytest.raises(RuntimeError, match="backend offline"):
        process_video(
            video,
            config(),
            tmp_path / "out",
            detector=FixedDetector(),
            event_sink=unavailable,
            save_video=False,
        )
    out = next((tmp_path / "out").iterdir())
    assert len((out / "events.jsonl").read_text().splitlines()) == 1
    assert (out / "failure.json").exists()
    assert not (out / "summary.json").exists()


def test_missing_and_empty_video(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_video(tmp_path / "absent.mp4", config(), tmp_path, detector=FixedDetector())
    video = tmp_path / "empty.mp4"
    video.touch()
    with pytest.raises(ValueError, match="Cannot open"):
        process_video(video, config(), tmp_path / "out", detector=FixedDetector())


def test_independent_runs_and_no_video_export(tmp_path):
    video = tmp_path / "input.mp4"
    make_video(video)
    summaries = [
        process_video(video, config(), tmp_path / "out", detector=FixedDetector(), save_video=False)
        for _ in range(2)
    ]
    assert summaries[0]["run_id"] != summaries[1]["run_id"]
    assert all(s["event_count"] == 1 and s["annotated_video"] is None for s in summaries)


@pytest.mark.parametrize("person_inside", [False, None])
def test_negative_scenarios_export_no_alert(tmp_path, person_inside):
    video = tmp_path / "input.mp4"
    make_video(video)

    class NegativeDetector:
        def detect(self, frame):
            return [] if person_inside is None else [Detection(1, 0.9, (0.1, 0.2, 0.3, 0.8))]

    summary = process_video(
        video, config(), tmp_path / "out", detector=NegativeDetector(), save_video=False
    )
    assert summary["event_count"] == 0
    assert (Path(summary["output_dir"]) / "events.jsonl").read_text() == ""


def test_invalid_fps_releases_capture(tmp_path, monkeypatch):
    video = tmp_path / "input.mp4"
    video.touch()

    class BadCapture:
        released = False

        def isOpened(self):
            return True

        def get(self, key):
            return float("nan")

        def release(self):
            self.released = True

    capture = BadCapture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda source: capture)
    with pytest.raises(ValueError, match="FPS"):
        process_video(video, config(), tmp_path / "out", detector=FixedDetector())
    assert capture.released


def test_redaction_does_not_modify_model_frame():
    from schoolguard_ai.rules import ZoneMonitor
    from schoolguard_ai.worker import render

    frame = np.zeros((240, 320, 3), dtype=np.uint8)
    # Fine alternating pattern disappears after pixelation.
    frame[40:200:2, 190:240:2] = 255
    original = frame.copy()
    detections = FixedDetector().detect(frame)
    result = ZoneMonitor(config()).update(0, detections)
    redacted = render(frame, config(), detections, result, 0)
    plain = render(frame, replace(config(), redact_people=False), detections, result, 0)
    assert np.array_equal(frame, original)
    assert not np.array_equal(redacted[60:160, 200:230], plain[60:160, 200:230])
