"""Integration contract for the home webcam/video MVP.

These tests are intentionally written before the contributor branches are merged.
They define the public runtime that the integrated application must expose.
"""

from __future__ import annotations

import importlib
import json
import os
import sys
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'schoolguard-test.db'}")
    monkeypatch.setenv("UPLOAD_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("SCHOOLGUARD_ADMIN_USER", "admin")
    monkeypatch.setenv("SCHOOLGUARD_ADMIN_PASSWORD", "test-password")
    monkeypatch.setenv("SCHOOLGUARD_ENV", "test")

    for name in ("main", "video_analysis"):
        sys.modules.pop(name, None)
    module = importlib.import_module("main")
    with TestClient(module.app) as test_client:
        yield test_client


def login(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/token",
        data={"username": "admin", "password": "test-password"},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_health_describes_home_monitor_runtime(client: TestClient):
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "mode": "home-monitor",
        "sources": ["video", "webcam"],
    }


def test_root_serves_single_integrated_web_application(client: TestClient):
    response = client.get("/")

    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    page = response.text.lower()
    assert "webcam" in page
    assert "video" in page
    assert "khu vực" in page


def test_dashboard_summary_uses_persisted_events(client: TestClient):
    headers = login(client)

    response = client.get("/api/dashboard/summary", headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total_events"] == 0
    assert payload["today_events"] == 0
    assert payload["sources"] == {"video": 0, "camera": 0}


def test_home_detection_routes_require_authentication(client: TestClient):
    routes = {route.path for route in client.app.routes}
    assert "/api/videos/analyze" in routes
    assert "/api/live/detect" in routes

    assert client.get("/api/events").status_code == 401


def test_sample_videos_are_listed_without_exposing_arbitrary_files(client: TestClient):
    response = client.get("/api/test-videos")

    assert response.status_code == 200
    assert response.json() == {
        "videos": ["Video1.mp4", "Video2.mp4", "Video3.mp4"]
    }
    assert client.get("/api/test-videos/not-allowed.mp4").status_code == 404


def test_event_evidence_cannot_escape_upload_directory(client: TestClient):
    headers = login(client)
    module = sys.modules["main"]
    with module.SessionLocal() as db:
        event = module.DetectionEventDB(
            source_type="video",
            source_id="tampered-record.mp4",
            zone_id="zone-1",
            zone_name="Vùng 1",
            object_type="person",
            image_path=str(module.BASE_DIR / "README.md"),
        )
        db.add(event)
        db.commit()
        event_id = event.id

    response = client.get(f"/api/events/{event_id}/image", headers=headers)

    assert response.status_code == 400
    assert response.json()["detail"] == "Đường dẫn ảnh sự kiện không hợp lệ"


def test_detection_event_status_note_and_activity_are_persisted(client: TestClient):
    headers = login(client)
    module = sys.modules["main"]
    evidence = module.UPLOAD_DIR / "event-workflow.jpg"
    evidence.write_bytes(b"jpeg")
    with module.SessionLocal() as db:
        event = module.DetectionEventDB(
            source_type="camera",
            source_id="webcam-home",
            zone_id="front-door",
            zone_name="Cửa chính",
            object_type="person",
            image_path=str(evidence),
        )
        db.add(event)
        db.commit()
        event_id = event.id

    response = client.put(
        f"/api/events/{event_id}/status",
        headers=headers,
        json={"status": "Đang xử lý", "note": "Đã kiểm tra camera cửa chính."},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "Đang xử lý"
    assert payload["note"] == "Đã kiểm tra camera cửa chính."
    assert payload["activities"][-1]["status"] == "Đang xử lý"
    assert payload["activities"][-1]["actor"] == "admin"
    assert "Đã kiểm tra" in payload["activities"][-1]["note"]

    persisted = client.get("/api/events", headers=headers).json()[0]
    assert persisted["status"] == "Đang xử lý"
    assert persisted["note"] == "Đã kiểm tra camera cửa chính."
    assert len(persisted["activities"]) == 1
    assert len(client.get("/api/events?status=Đang xử lý", headers=headers).json()) == 1
    assert client.get("/api/events?status=Đã hoàn tất", headers=headers).json() == []
    repeated = client.put(
        f"/api/events/{event_id}/status",
        headers=headers,
        json={"status": "Đang xử lý", "note": "Đã kiểm tra camera cửa chính."},
    )
    assert len(repeated.json()["activities"]) == 1


def test_detection_event_rejects_unknown_status(client: TestClient):
    headers = login(client)
    module = sys.modules["main"]
    with module.SessionLocal() as db:
        event = module.DetectionEventDB(
            source_type="video",
            source_id="sample.mp4",
            zone_id="zone-1",
            zone_name="Vùng 1",
            object_type="person",
            image_path=str(module.UPLOAD_DIR / "missing.jpg"),
        )
        db.add(event)
        db.commit()
        event_id = event.id

    response = client.put(
        f"/api/events/{event_id}/status",
        headers=headers,
        json={"status": "Trạng thái tùy ý", "note": ""},
    )

    assert response.status_code == 422


def test_legacy_detection_event_table_gets_workflow_columns(client, tmp_path, monkeypatch):
    module = sys.modules["main"]
    legacy_engine = module.create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE detection_events (id INTEGER PRIMARY KEY, image_path VARCHAR NOT NULL)"
        )
        connection.exec_driver_sql(
            "INSERT INTO detection_events (id, image_path) VALUES (1, 'legacy.jpg')"
        )
    monkeypatch.setattr(module, "engine", legacy_engine)

    module._migrate_detection_event_columns()

    columns = {
        column["name"] for column in module.inspect(legacy_engine).get_columns("detection_events")
    }
    assert {"status", "note"}.issubset(columns)
    with legacy_engine.connect() as connection:
        activity = connection.exec_driver_sql(
            "SELECT actor, action, status FROM event_activities WHERE event_id = 1"
        ).one()
    assert activity == ("system", "Sự kiện trước khi nâng cấp", "Chưa xử lý")


def test_video_analysis_route_persists_event_and_serves_result(client, monkeypatch):
    headers = login(client)
    module = sys.modules["main"]
    output = module.UPLOAD_DIR / "worker-result.mp4"
    evidence = module.UPLOAD_DIR / "worker-evidence.jpg"
    output.write_bytes(b"annotated-video")
    evidence.write_bytes(b"jpeg")

    monkeypatch.setattr(module, "validate_video_duration", lambda *_args, **_kwargs: 2.0)
    monkeypatch.setattr(
        module,
        "analyze_person_video",
        lambda *_args, **_kwargs: {
            "status": "completed",
            "duration_seconds": 2.0,
            "processed_frames": 20,
            "people_count": 1,
            "vehicle_counts": {},
            "uniform_groups": [],
            "events": [
                {
                    "zone_id": "front-door",
                    "zone_name": "Cửa chính",
                    "object_type": "person",
                    "track_id": 7,
                    "media_offset_seconds": 1.2,
                    "image_path": evidence,
                }
            ],
            "engine": "be1-yolo-bytetrack",
            "browser_playable": True,
            "output_path": output,
        },
    )
    zones = [
        {
            "id": "front-door",
            "name": "Cửa chính",
            "x": 0.1,
            "y": 0.1,
            "width": 0.5,
            "height": 0.5,
            "classes": [0],
        }
    ]

    response = client.post(
        "/api/videos/analyze",
        headers=headers,
        data={"zones": json.dumps(zones)},
        files={"file": ("sample.mp4", b"fake-video", "video/mp4")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["engine"] == "be1-yolo-bytetrack"
    assert payload["events"][0]["event_id"] > 0
    result = client.get(payload["annotated_video_url"], headers=headers)
    assert result.status_code == 200
    assert result.content == b"annotated-video"
    events = client.get("/api/events", headers=headers).json()
    assert len(events) == 1
    assert events[0]["status"] == "Chưa xử lý"
    assert events[0]["activities"][0]["actor"] == "system"


def test_live_frame_route_runs_the_webcam_contract(client, monkeypatch):
    headers = login(client)
    module = sys.modules["main"]
    monkeypatch.setattr(
        module,
        "detect_live_frame_jpeg",
        lambda *_args, **_kwargs: {
            "width": 640,
            "height": 360,
            "detections": [
                {
                    "label": "Người",
                    "confidence": 0.9,
                    "box": [10, 20, 100, 200],
                    "color": "#2563EB",
                    "class_id": 0,
                    "track_id": 3,
                }
            ],
            "events": [],
        },
    )

    response = client.post(
        "/api/live/detect",
        headers=headers,
        data={"stream_id": "webcam-test", "selected_classes": "[0]"},
        files={"file": ("frame.jpg", b"jpeg", "image/jpeg")},
    )

    assert response.status_code == 200
    assert response.json()["detections"][0]["label"] == "Người"


def test_login_is_rate_limited_after_repeated_failures(client):
    for _ in range(5):
        response = client.post("/token", data={"username": "admin", "password": "wrong"})
        assert response.status_code == 401

    response = client.post("/token", data={"username": "admin", "password": "wrong"})
    assert response.status_code == 429


def test_old_video_results_are_bounded_and_cleaned(client, monkeypatch):
    module = sys.modules["main"]
    old_output = module.UPLOAD_DIR / "old-result.mp4"
    new_output = module.UPLOAD_DIR / "new-result.mp4"
    old_output.write_bytes(b"old")
    new_output.write_bytes(b"new")
    module.video_results.clear()
    module.video_results.update(
        {
            "old": {
                "summary": {},
                "output_path": old_output,
                "created_at": datetime.now(UTC) - timedelta(minutes=2),
            },
            "new": {
                "summary": {},
                "output_path": new_output,
                "created_at": datetime.now(UTC),
            },
        }
    )
    monkeypatch.setattr(module, "MAX_VIDEO_RESULTS", 1)

    module._cleanup_video_results()

    assert set(module.video_results) == {"new"}
    assert not old_output.exists()
    assert new_output.exists()


def test_stale_failed_worker_run_is_removed_recursively(client):
    module = sys.modules["main"]
    run_dir = module.VIDEO_RUNS_DIR / "failed-run"
    snapshot = run_dir / "snapshots" / "event.jpg"
    failure = run_dir / "failure.json"
    snapshot.parent.mkdir(parents=True)
    snapshot.write_bytes(b"jpeg")
    failure.write_text('{"status":"failed"}', encoding="utf-8")
    old_time = (
        datetime.now(UTC).timestamp()
        - module.VIDEO_RESULT_TTL.total_seconds()
        - 60
    )
    os.utime(failure, (old_time, old_time))

    module._cleanup_stale_video_artifacts()

    assert not run_dir.exists()
