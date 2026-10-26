from schoolguard.schemas import COCO_DETECTION_MODELS, POSE_MODELS, JobRequest


def test_yolo26_models_are_explicit_and_pose_is_required_for_fall_rules():
    assert "yolo26n" in COCO_DETECTION_MODELS
    assert "yolo26s" in COCO_DETECTION_MODELS
    assert "yolo26n-pose" in POSE_MODELS
    assert JobRequest(source_id="clip", model="yolo26n-pose", detect_falls=True).model == "yolo26n-pose"
    assert JobRequest(source_id="clip", model="yolo26n-pose", detect_interactions=True).model == "yolo26n-pose"
    try:
        JobRequest(source_id="clip", model="yolo26n", detect_falls=True)
    except ValueError as exc:
        assert "-pose" in str(exc)
    else:
        raise AssertionError("Non-pose checkpoint cannot enable fall detection")


def test_optional_yolo26_weights_are_advertised_and_job_can_select_them(client, app, request_data):
    for name in ("yolo26n", "yolo26s", "yolo26n-pose"):
        assert client.get("/api/system").json()["models"][name] is False
        (app.state.settings.models / (name + ".pt")).write_bytes(b"test stub")
    status = client.get("/api/system").json()
    assert all(status["models"][name] for name in ("yolo26n", "yolo26s", "yolo26n-pose"))
    request_data.update({"model": "yolo26n-pose", "detect_falls": True})
    assert client.post("/api/jobs", json=request_data).status_code == 202
