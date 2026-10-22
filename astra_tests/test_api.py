from fastapi.testclient import TestClient


def test_login_required_and_logout(client):
    assert client.get("/api/me").json()["role"] == "admin"
    assert client.post("/api/logout").status_code == 200
    for path in ["/api/jobs", "/api/alerts", "/api/sources", "/api/export/alerts.csv"]:
        assert client.get(path).status_code == 401


def test_bad_login_and_rate_limit(app):
    with TestClient(app) as c:
        for _ in range(8):
            assert (
                c.post("/api/login", json={"username": "no", "password": "bad"}).status_code == 401
            )
        assert c.post("/api/login", json={"username": "no", "password": "bad"}).status_code == 429


def test_viewer_authorization(client, request_data):
    assert (
        client.post(
            "/api/users",
            json={"username": "viewer", "password": "test-password-123", "role": "viewer"},
        ).status_code
        == 201
    )
    client.post("/api/logout")
    client.post("/api/login", json={"username": "viewer", "password": "test-password-123"})
    assert client.get("/api/jobs").status_code == 200
    assert client.get("/api/users").status_code == 403
    assert client.post("/api/jobs", json=request_data).status_code == 403
    assert client.patch("/api/alerts/missing", json={"status": "resolved"}).status_code == 403


def test_csrf_and_host(client, request_data):
    assert (
        client.post(
            "/api/jobs", json=request_data, headers={"Origin": "https://evil.test"}
        ).status_code
        == 403
    )
    assert client.get("/api/health", headers={"Host": "evil.test"}).status_code == 400


def test_sources_pagination_and_no_path_disclosure(client):
    response = client.get("/api/sources?limit=1").json()
    assert response["total"] == 2
    assert len(response["items"]) == 1
    assert "path" not in response["items"][0]
    source = response["items"][0]
    meta = client.get("/api/sources/" + source["id"]).json()
    assert "path" not in meta and meta["width"] == 160
    assert (
        client.get("/api/sources/" + source["id"] + "/thumbnail").headers["content-type"]
        == "image/jpeg"
    )
    assert client.get("/api/sources?limit=1000").status_code == 422


def test_unknown_and_path_escape_sources(client, app, tmp_path):
    assert client.get("/api/sources/missing").status_code == 404
    app.state.db.execute(
        "INSERT INTO sources VALUES(?,?,?,?,?)",
        ("outside", "outside", str(tmp_path.parent), "frames", "testing"),
    )
    assert client.get("/api/sources/outside").status_code == 403


def test_queue_limit_and_cancel(client, request_data):
    jobs = [client.post("/api/jobs", json=request_data) for _ in range(10)]
    assert all(r.status_code == 202 for r in jobs)
    assert client.post("/api/jobs", json=request_data).status_code == 429
    cancelled = client.post("/api/jobs/" + jobs[0].json()["id"] + "/cancel").json()
    assert cancelled["status"] == "cancelled"
    assert client.post("/api/jobs", json=request_data).status_code == 202


def test_upload_validation(client):
    assert (
        client.post("/api/sources/upload", files={"file": ("evil.exe", b"bad")}).status_code == 422
    )
    assert (
        client.post("/api/sources/upload", files={"file": ("broken.mp4", b"bad")}).status_code
        == 422
    )


def test_upload_valid_video(client, app):
    path = app.state.settings.data_root / "training/videos/01_001.avi"
    result = client.post(
        "/api/sources/upload", files={"file": ("../../test.avi", path.read_bytes(), "video/avi")}
    )
    assert result.status_code == 201
    row = result.json()
    assert row["name"] == "test.avi"
    assert client.get("/api/sources/" + row["id"]).status_code == 200


def test_completed_job_evidence_review_and_export(client, app, finished):
    job = client.get("/api/jobs/" + finished).json()
    assert job["status"] == "completed", job.get("error")
    assert job["summary"]["processed_frames"] == 20
    assert job["summary"]["alerts"] == 1
    alerts = client.get("/api/alerts?job_id=" + finished).json()["items"]
    alert = alerts[0]
    assert alert["video_time"] == 0.5
    assert client.get("/api/alerts/" + alert["id"] + "/evidence").status_code == 200
    assert (
        client.patch(
            "/api/alerts/" + alert["id"],
            json={"status": "false_positive", "note": '=HYPERLINK("x")'},
        ).status_code
        == 200
    )
    assert client.get("/api/alerts?status=false_positive").json()["total"] == 1
    assert "'=HYPERLINK" in client.get("/api/export/alerts.csv").text
    assert client.get("/api/audit").json()[0]["action"] == "review_alert"
    video = client.get(
        "/api/jobs/" + finished + "/files/result.mp4", headers={"Range": "bytes=0-99"}
    )
    assert video.status_code == 206 and len(video.content) == 100
    assert client.get("/api/jobs/" + finished + "/files/config.json").status_code == 200
    assert client.get("/api/jobs/" + finished + "/files/encoder.log").status_code == 404
    assert (
        client.get("/api/jobs/" + finished + "/files/..%2F..%2Fadmin-password.txt").status_code
        == 404
    )


def test_session_expiry(client, app):
    app.state.db.execute("UPDATE sessions SET expires=0")
    assert client.get("/api/me").status_code == 401
