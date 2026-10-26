import json
import uuid

import cv2
import numpy as np

from schoolguard.db import now


def test_weapon_gallery_evidence_review_and_account_isolation(client, app, finished):
    assert client.get("/admin").status_code == 200
    directory = app.state.settings.runtime / "jobs" / finished
    evidence = "weapon-gallery-test.jpg"
    assert cv2.imwrite(str(directory / evidence), np.full((120, 160, 3), 180, dtype=np.uint8))
    alert_id = uuid.uuid4().hex
    app.state.db.execute(
        "INSERT INTO alerts(id,job_id,created_at,video_time,zone,track_id,confidence,"
        "bbox,dwell,evidence,event_type,severity,details) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (alert_id, finished, now(), 1.4, "Vật thể nghi hung khí", -201, .88,
         json.dumps([.25, .25, .4, .5]), .6, evidence, "weapon", "urgent",
         json.dumps({"category": "blade", "review_required": True})),
    )
    gallery = client.get(f"/api/jobs/{finished}/weapons")
    assert gallery.status_code == 200
    assert gallery.json()["total"] == 1
    assert gallery.json()["items"][0]["id"] == alert_id
    crop = client.get(f"/api/alerts/{alert_id}/object")
    assert crop.status_code == 200
    assert crop.headers["content-type"] == "image/jpeg"
    assert len(crop.content) > 100
    assert client.patch(f"/api/alerts/{alert_id}", json={
        "status": "false_positive", "note": "Vật dụng trong nhà",
    }).status_code == 200
    assert client.get(f"/api/jobs/{finished}/weapons").json()["items"][0]["status"] == "false_positive"

    other = client.post("/api/register", json={
        "username": "weapon_other", "password": "strong-other-password-123",
        "display_name": "Người khác", "email": "other@example.test", "consent": True,
    })
    assert other.status_code == 201
    assert client.get("/admin").status_code == 403
    assert client.get(f"/api/jobs/{finished}/weapons").status_code == 404
    assert client.get(f"/api/alerts/{alert_id}/object").status_code == 404
    assert client.patch(f"/api/alerts/{alert_id}", json={
        "status": "resolved", "note": "Không có quyền",
    }).status_code == 404
