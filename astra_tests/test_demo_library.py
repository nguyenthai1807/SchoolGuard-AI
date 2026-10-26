from schoolguard.db import now


def _clip_with_fire(app, index):
    db = app.state.db
    original = db.one("SELECT * FROM sources WHERE split='training' LIMIT 1")
    source_id = f"demo-source-{index}"
    job_id = f"demo-job-{index}"
    user_id = db.one("SELECT id FROM users WHERE username='admin'")["id"]
    db.execute(
        "INSERT INTO sources(id,name,path,kind,split) VALUES(?,?,?,?,?)",
        (source_id, f"demo-{index}.avi", original["path"], "video", "training"),
    )
    db.execute(
        "INSERT INTO jobs(id,source_id,status,created_at,finished_at,config,user_id) "
        "VALUES(?,?,?,?,?,?,?)",
        (job_id, source_id, "completed", now(), now(), "{}", user_id),
    )
    db.execute(
        "INSERT INTO alerts(id,job_id,created_at,video_time,zone,track_id,confidence,"
        "bbox,dwell,evidence,event_type) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        (f"demo-alert-{index}", job_id, now(), 1.0, "", 0, 0.8,
         "[0,0,1,1]", 0.0, "evidence.jpg", "fire"),
    )
    return source_id, job_id


def _payload(source_id, job_id):
    return {
        "source_id": source_id,
        "capability": "fire",
        "evidence_job_id": job_id,
        "rights_note": "Clip nhóm tự quay, có quyền sử dụng.",
        "review_note": "Đã xem lại lửa ở giây thứ 1 và khung cảnh báo tương ứng.",
        "review_confirmed": True,
    }


def test_admin_star_requires_evidence_and_is_removable(client, app):
    source_id, job_id = _clip_with_fire(app, 1)
    assert client.get("/api/admin/demo-videos").json()["items"] == []
    assert client.get(f"/api/admin/demo-videos/jobs/{source_id}").json()["items"][0]["events"] == [
        {"event_type": "fire", "count": 1}
    ]
    payload = _payload(source_id, job_id)
    assert client.post("/api/admin/demo-videos", json=payload | {"review_confirmed": False}).status_code == 422
    assert client.post("/api/admin/demo-videos", json=payload | {"evidence_job_id": "wrong"}).status_code == 422
    assert client.post("/api/admin/demo-videos", json=payload | {"capability": "fall"}).status_code == 422
    assert client.post("/api/admin/demo-videos", json=payload).status_code == 201
    listed = client.get("/api/admin/demo-videos").json()
    assert listed["limit_per_capability"] == 5
    assert listed["items"][0]["source_id"] == source_id
    assert "path" not in listed["items"][0]
    assert client.delete(f"/api/admin/demo-videos/fire/{source_id}").status_code == 200
    assert client.get("/api/admin/demo-videos").json()["items"] == []


def test_admin_demo_limit_and_customer_isolation(client, app):
    for index in range(6):
        source_id, job_id = _clip_with_fire(app, index)
        response = client.post("/api/admin/demo-videos", json=_payload(source_id, job_id))
        assert response.status_code == (201 if index < 5 else 409)
    assert len(client.get("/api/admin/demo-videos").json()["items"]) == 5
    assert client.post("/api/users", json={
        "username": "demo_viewer", "password": "test-password-123", "role": "viewer"
    }).status_code == 201
    client.post("/api/logout")
    assert client.post("/api/login", json={
        "username": "demo_viewer", "password": "test-password-123"
    }).status_code == 200
    assert client.get("/api/admin/demo-videos").status_code == 403
    assert client.get(f"/api/admin/demo-videos/jobs/{source_id}").status_code == 403
    assert client.post("/api/admin/demo-videos", json=_payload(source_id, job_id)).status_code == 403
    assert client.delete(f"/api/admin/demo-videos/fire/{source_id}").status_code == 403


def test_research_demo_requires_academic_only_label(client, app):
    source_id, job_id = _clip_with_fire(app, "academic")
    app.state.db.execute("UPDATE sources SET split='research',name='[research] academic.mp4' WHERE id=?", (source_id,))
    payload = _payload(source_id, job_id)
    assert client.post("/api/admin/demo-videos", json=payload).status_code == 422
    assert client.post("/api/admin/demo-videos", json=payload | {
        "academic_only": True,
        "rights_note": "Research/education use only; not for Store advertising.",
    }).status_code == 201
    listed = client.get("/api/admin/demo-videos").json()["items"]
    assert listed[0]["academic_only"] == 1


def test_false_positive_weapon_alert_cannot_be_starred(client, app):
    source_id, job_id = _clip_with_fire(app, "weapon-false-positive")
    app.state.db.execute(
        "UPDATE alerts SET event_type='weapon',status='false_positive' WHERE job_id=?",
        (job_id,),
    )
    payload = _payload(source_id, job_id) | {"capability": "weapon"}
    assert client.post("/api/admin/demo-videos", json=payload).status_code == 422
    assert client.get("/api/admin/demo-videos").json()["items"] == []


def test_research_interaction_demo_can_be_starred_only_as_academic(client, app):
    source_id, job_id = _clip_with_fire(app, "interaction")
    app.state.db.execute(
        "UPDATE sources SET split='research',name='[research] staged-interaction.mp4' WHERE id=?",
        (source_id,),
    )
    app.state.db.execute(
        "UPDATE alerts SET event_type='vigorous_interaction' WHERE job_id=?",
        (job_id,),
    )
    payload = _payload(source_id, job_id) | {
        "capability": "interaction",
        "rights_note": "Research/education use only; no Store advertising.",
    }
    assert client.post("/api/admin/demo-videos", json=payload).status_code == 422
    assert client.post("/api/admin/demo-videos", json=payload | {
        "academic_only": True,
    }).status_code == 201
    assert client.get("/api/admin/demo-videos").json()["items"][0]["capability"] == "interaction"
