import numpy as np
from conftest import FakeDetector

from schoolguard.media import Reader
from schoolguard.worker import Worker, draw


def test_redaction_preserves_original():
    image = np.random.default_rng(2).integers(0, 256, (120, 160, 3), dtype=np.uint8)
    original = image.copy()
    detections = [{"track_id": 1, "confidence": 0.9, "bbox": [0.1, 0.1, 0.9, 0.9]}]
    output = draw(image, detections, [], set(), True)
    assert np.array_equal(image, original)
    assert not np.array_equal(output[30:90, 40:120], original[30:90, 40:120])


def run_job(client, app, payload, detector=FakeDetector):
    ident = client.post("/api/jobs", json=payload).json()["id"]
    row = app.state.db.one("SELECT * FROM jobs WHERE id=?", (ident,))
    Worker(app.state.db, app.state.settings, detector).run(row)
    return client.get("/api/jobs/" + ident).json()


def test_detection_only_has_no_alerts(client, app, request_data):
    request_data["zones"] = []
    result = run_job(client, app, request_data)
    assert result["status"] == "completed"
    assert result["events"] == 0 and result["summary"]["peak_people"] == 1
    gallery = client.get(f"/api/jobs/{result['id']}/people")
    assert gallery.status_code == 200
    assert gallery.json()["count"] == 1
    track = gallery.json()["items"][0]
    assert client.get(f"/api/jobs/{result['id']}/people/{track['track_id']}/image").headers[
        "content-type"] == "image/jpeg"
    assert client.get(f"/api/jobs/{result['id']}/people/999/image").status_code == 404


def test_empty_scene_no_false_alert(client, app, request_data):
    class Empty(FakeDetector):
        def __call__(self, frame):
            return []

    result = run_job(client, app, request_data, Empty)
    assert result["status"] == "completed"
    assert result["summary"]["peak_people"] == 0 and result["events"] == 0


def test_redacted_job_never_saves_person_snapshots(client, app, request_data):
    request_data["redact"] = True
    result = run_job(client, app, request_data)
    assert result["status"] == "completed"
    assert client.get(f"/api/jobs/{result['id']}/people").json()["available"] is False
    assert not list((app.state.settings.runtime / "jobs" / result["id"]).glob("person-*.jpg"))


def test_stride_duration_and_frame_count(client, app, request_data):
    request_data.update(stride=3, max_seconds=1)
    result = run_job(client, app, request_data)
    assert result["status"] == "completed"
    assert result["summary"]["inferred_frames"] == 4
    assert result["summary"]["processed_frames"] == 10
    with Reader(app.state.settings.runtime / "jobs" / result["id"] / "result.mp4") as reader:
        assert reader.count == 10 and reader.fps == 10


def test_sequence_input(client, app, request_data):
    source = client.get("/api/sources?split=testing").json()["items"][0]
    request_data.update(source_id=source["id"], sequence_fps=5, dwell_seconds=0)
    result = run_job(client, app, request_data)
    assert result["status"] == "completed"
    assert result["summary"]["fps_assumed"] is True
    assert result["summary"]["source_fps"] == 5


def test_detector_failure_is_recorded(client, app, request_data):
    class Broken(FakeDetector):
        def __call__(self, frame):
            raise RuntimeError("test detector failed")

    result = run_job(client, app, request_data, Broken)
    assert result["status"] == "failed"
    assert "test detector failed" in result["error"]


def test_cancelled_job_no_completed_video(client, app, request_data):
    ident = client.post("/api/jobs", json=request_data).json()["id"]
    client.post("/api/jobs/" + ident + "/cancel")
    row = app.state.db.one("SELECT * FROM jobs WHERE id=?", (ident,))
    Worker(app.state.db, app.state.settings, FakeDetector).run(row)
    assert client.get("/api/jobs/" + ident).json()["status"] == "cancelled"
    assert client.get("/api/jobs/" + ident + "/files/result.mp4").status_code == 404


def test_restart_marks_interrupted_job_failed(client, app, request_data):
    ident = client.post("/api/jobs", json=request_data).json()["id"]
    app.state.db.execute("UPDATE jobs SET status='running' WHERE id=?", (ident,))
    worker = Worker(app.state.db, app.state.settings, FakeDetector)
    worker.start()
    worker.close()
    assert client.get("/api/jobs/" + ident).json()["status"] == "failed"


def test_preview_windows_file_lock_does_not_fail_video(client, app, request_data, monkeypatch):
    from pathlib import Path

    original = Path.replace

    def locked_preview(self, target):
        if self.name == "preview.tmp":
            raise PermissionError("simulated Windows reader lock")
        return original(self, target)

    monkeypatch.setattr(Path, "replace", locked_preview)
    result = run_job(client, app, request_data)
    assert result["status"] == "completed"
    assert result["summary"]["preview_write_retries"] > 0


def test_video_deduplicates_people_and_recovers_fragmented_raw_ids(client, app, request_data):
    class Fragmented(FakeDetector):
        def __init__(self, *_): self.frame = 0
        def __call__(self, frame):
            self.frame += 1
            person = {"track_id": self.frame, "confidence": .9, "class_id": 0,
                      "bbox": [.2, .2, .4, .8]}
            return [person, {**person, "track_id": self.frame + 100, "confidence": .8},
                    {"track_id": 999, "class_id": 2, "confidence": .9, "bbox": [.6, .2, .9, .8]}]
    request_data.update(zones=[])
    result = run_job(client, app, request_data, Fragmented)
    assert result['status'] == 'completed'
    assert result['summary']['peak_people'] == 1
    assert result['summary']['tracked_people'] == 1
    assert result['people'] == 1


def test_video_face_matching_receives_stable_current_body_tracks(client, app, request_data, monkeypatch):
    calls = []
    class Ledger:
        def __init__(self, *_): self.records = {}
        def observe_people(self, people, stamp): calls.append(('observe', people, stamp))
        def update(self, frame, stamp, people=None):
            calls.append(('face', people, stamp))
            return {'visible': [], 'total': 0}
    monkeypatch.setattr('schoolguard.worker.FaceLedger', Ledger)
    ident = client.post('/api/jobs', json=request_data).json()['id']
    row = app.state.db.one('SELECT * FROM jobs WHERE id=?', (ident,))
    import json
    config = json.loads(row['config'])
    config.update(recognize_faces=True, stride=3)
    row['config'] = json.dumps(config)
    Worker(app.state.db, app.state.settings, FakeDetector, face_factory=lambda _: None).run(row)
    assert any(kind == 'observe' for kind, _, _ in calls)
    assert all(people and people[0]['track_id'] == 1 for _, people, _ in calls)
    assert all(round(stamp * 10) % 3 == 0 for _, _, stamp in calls)


def test_skipped_frame_never_labels_stale_count_as_current(client, app, request_data, monkeypatch):
    import cv2
    labels = []
    original = cv2.putText
    def capture(image, text, *args, **kwargs):
        if 'persons' in text: labels.append(text)
        return original(image, text, *args, **kwargs)
    monkeypatch.setattr(cv2, 'putText', capture)
    request_data.update(stride=3)
    result = run_job(client, app, request_data)
    assert result['status'] == 'completed'
    assert any('persons --' in text and 'skipped' in text for text in labels)
    assert not any('persons 1' in text and 'skipped' in text for text in labels)
