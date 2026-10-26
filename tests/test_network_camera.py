import base64
import importlib
import threading
import time

import cv2
import numpy as np
import pytest

from schoolguard.network_camera import NetworkCamera, validate_camera_url
from schoolguard.schemas import JobRequest
from schoolguard.db import now


@pytest.mark.parametrize("url", ["http://192.168.1.20:8080/video", "rtsp://user:pass@10.0.0.8:554/stream1", "http://172.16.1.2/feed"])
def test_accepts_private_camera_addresses(url):
    assert validate_camera_url(url) == url


@pytest.mark.parametrize("url", ["file:///secret", "http://127.0.0.1", "http://example.com", "http://8.8.8.8", "http://169.254.1.1", "http://192.168.1.2:99999", "rtsp://224.0.0.1/live"])
def test_rejects_invalid_camera_addresses(url):
    with pytest.raises(ValueError):
        validate_camera_url(url)


def test_source_url_is_not_serialized():
    config = JobRequest(source_id="live", camera_url="rtsp://u:secret@192.168.1.2/live")
    assert "secret" not in config.model_dump_json()
    assert "camera_url" not in config.model_dump()


def test_network_source_resize_and_release(monkeypatch):
    class Capture:
        closed = False
        def isOpened(self): return True
        def set(self, *_args): pass
        def read(self):
            time.sleep(.01)
            return True, np.zeros((1440, 2560, 3), dtype=np.uint8)
        def release(self): self.closed = True
    monkeypatch.setattr("schoolguard.network_camera.probe_camera", lambda _url: None)
    capture = Capture()
    monkeypatch.setattr(cv2, "VideoCapture", lambda *_args: capture)
    source = NetworkCamera("http://192.168.1.2/video")
    data = source.jpeg()
    decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    assert decoded.shape[:2] == (720, 1280)
    source.close()
    assert capture.closed


def test_remote_start_analyze_preview_and_stop(tmp_path, monkeypatch):
    from schoolguard.app import create_app
    from schoolguard.config import Settings
    module = importlib.import_module("schoolguard.app")
    ok, data = cv2.imencode('.jpg', np.zeros((120, 160, 3), dtype=np.uint8))
    assert ok
    class Source:
        closed = False
        def __init__(self, url): pass
        def jpeg(self): return data.tobytes()
        def close(self): self.closed = True
    class Detector:
        def __init__(self, *_args): pass
        def __call__(self, _frame): return []
    monkeypatch.setattr(module, 'NetworkCamera', Source)
    app = create_app(Settings(runtime=tmp_path/'runtime', models=tmp_path/'models',
                              data_root=tmp_path/'data', start_worker=False), detector_factory=Detector)
    app.state.db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'admin','x','admin')")
    def endpoint(path):
        return next(r.endpoint for r in app.routes if r.path == path)
    current = {'id': 1, 'username': 'admin', 'role': 'admin'}
    created = endpoint('/api/live/start')(JobRequest(source_id='live', camera_url='http://192.168.1.2/video'), current)
    ident = created['id']
    source = app.state.live_sessions[ident]['source']
    result = endpoint('/api/live/{ident}/remote-frame')(ident, current)
    assert result['people'] == 0
    assert base64.b64decode(result['preview']) == data.tobytes()
    assert endpoint('/api/live/{ident}/stop')(ident, current) == {'ok': True}
    assert source.closed


def test_camera_credentials_are_encoded_and_never_serialized():
    from schoolguard.network_camera import camera_credentials
    url = camera_credentials("http://192.168.1.2/live.flv", "user@home", "p:a/ss#")
    assert url == "http://user%40home:p%3Aa%2Fss%23@192.168.1.2/live.flv"
    config = JobRequest(source_id="live", camera_url=url, camera_username="user@home", camera_password="secret")
    assert 'secret' not in config.model_dump_json()
    assert 'camera_password' not in config.model_dump()


@pytest.mark.parametrize('status,content,expected', [(401, '', 'đăng nhập'), (404, '', '404'), (200, 'text/html', 'trang xem'), (302, '', 'chuyển hướng')])
def test_probe_reports_actionable_errors_without_secrets(monkeypatch, status, content, expected):
    from schoolguard.network_camera import probe_camera
    class Response:
        status_code = status
        def __init__(self):
            self.headers = {'Content-Type': content}
        def __enter__(self): return self
        def __exit__(self, *_args): pass
    class Session:
        def __enter__(self): return self
        def __exit__(self, *_args): pass
        def get(self, url, **kwargs):
            assert 'secret' not in url
            assert kwargs['auth'] == ('user', 'secret')
            assert kwargs['allow_redirects'] is False
            return Response()
    monkeypatch.setattr('schoolguard.network_camera.requests.Session', Session)
    with pytest.raises(ValueError, match=expected) as exc:
        probe_camera('http://user:secret@192.168.1.2/live.flv')
    assert 'secret' not in str(exc.value)


def test_slow_consumer_gets_latest_frame_not_buffered_frames(monkeypatch):
    reached_latest = threading.Event()
    unblock = threading.Event()
    class Capture:
        count = 0
        closed = False
        def isOpened(self): return True
        def set(self, *_args): pass
        def read(self):
            self.count += 1
            if self.count <= 30:
                return True, np.full((120, 160, 3), self.count*5, dtype=np.uint8)
            reached_latest.set()
            unblock.wait(2)
            return False, None
        def release(self): self.closed = True
    cap = Capture()
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *_args: cap)
    monkeypatch.setattr('schoolguard.network_camera.probe_camera', lambda _url: None)
    source = NetworkCamera('http://192.168.1.2/live.flv')
    try:
        assert reached_latest.wait(2)
        decoded = cv2.imdecode(np.frombuffer(source.jpeg(), np.uint8), cv2.IMREAD_COLOR)
        assert decoded.mean() == pytest.approx(150, abs=2)
        # Repeated polling never advances through a historical queue.
        decoded = cv2.imdecode(np.frombuffer(source.jpeg(), np.uint8), cv2.IMREAD_COLOR)
        assert decoded.mean() == pytest.approx(150, abs=2)
    finally:
        unblock.set()
        source.close()
    assert cap.closed
    assert not source.reader.is_alive()


def test_disconnected_camera_does_not_return_old_frame(monkeypatch):
    class Capture:
        def isOpened(self): return True
        def set(self, *_args): pass
        def read(self): return False, None
        def release(self): pass
    monkeypatch.setattr(cv2, 'VideoCapture', lambda *_args: Capture())
    monkeypatch.setattr('schoolguard.network_camera.probe_camera', lambda _url: None)
    source = NetworkCamera('http://192.168.1.2/live.flv')
    try:
        with pytest.raises(ValueError, match='mất tín hiệu'):
            source.jpeg()
    finally:
        source.close()


@pytest.mark.parametrize('rotation', [0, 90, 180, 270])
@pytest.mark.parametrize('mirror', [False, True])
def test_rotation_and_mirror_apply_to_pixels_before_inference(rotation, mirror):
    source = object.__new__(NetworkCamera)
    source.rotation, source.mirror = rotation, mirror
    source.condition, source.stopped = threading.Condition(), threading.Event()
    source.failed = False
    source.received_at = time.monotonic()
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    frame[:60, :80] = [0, 0, 240]
    frame[60:, 80:] = [0, 240, 0]
    source.latest = frame
    expected = frame
    rotations = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180, 270: cv2.ROTATE_90_COUNTERCLOCKWISE}
    if rotation: expected = cv2.rotate(expected, rotations[rotation])
    if mirror: expected = cv2.flip(expected, 1)
    actual = cv2.imdecode(np.frombuffer(source.jpeg(), np.uint8), cv2.IMREAD_COLOR)
    assert actual.shape == expected.shape
    assert np.abs(actual.astype(float)-expected).mean() < 5


def test_portrait_keeps_detail():
    source = object.__new__(NetworkCamera)
    source.rotation, source.mirror = 0, False
    source.condition, source.stopped = threading.Condition(), threading.Event()
    source.failed = False
    source.received_at = time.monotonic()
    source.latest = np.zeros((1440, 1080, 3), dtype=np.uint8)
    actual = cv2.imdecode(np.frombuffer(source.jpeg(), np.uint8), cv2.IMREAD_COLOR)
    assert actual.shape[:2] == (1280, 960)


def test_portrait_phone_saves_two_faces_in_same_gallery(tmp_path, monkeypatch):
    from schoolguard.app import create_app
    from schoolguard.config import Settings
    module = importlib.import_module('schoolguard.app')
    ok, data = cv2.imencode('.jpg', np.zeros((1280, 960, 3), dtype=np.uint8))
    assert ok
    class Source:
        def __init__(self, _url): pass
        def jpeg(self): return data.tobytes()
        def close(self): pass
        def set_view(self, rotation, mirror):
            self.rotation, self.mirror = rotation, mirror
    class Detector:
        def __init__(self, *_args): pass
        def __call__(self, _frame): return []
    class Faces:
        def __init__(self, _settings): pass
        def __call__(self, _frame):
            return [{'bbox': [.1+i*.5, .1, .3+i*.5, .3], 'confidence': .95,
                     'embedding': np.eye(2, dtype=np.float32)[i], 'image': data.tobytes()} for i in range(2)]
    monkeypatch.setattr(module, 'NetworkCamera', Source)
    app = create_app(Settings(runtime=tmp_path/'runtime', models=tmp_path/'models',
                             data_root=tmp_path/'data', start_worker=False), detector_factory=Detector, face_factory=Faces)
    app.state.db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'admin','x','admin')")
    def endpoint(path): return next(r.endpoint for r in app.routes if r.path == path)
    current = {'id': 1, 'username': 'admin', 'role': 'admin'}
    ident = endpoint('/api/live/start')(JobRequest(source_id='live', camera_url='http://192.168.1.2/live.flv', recognize_faces=True), current)['id']
    for _ in range(2):
        app.state.live_sessions[ident]['analyzer'].last_face = -10
        result = endpoint('/api/live/{ident}/remote-frame')(ident, current)
    assert result['face_count_today'] == 2
    assert {f['number'] for f in result['faces']} == {1, 2}
    assert app.state.db.one("SELECT count(*) n FROM faces WHERE kind='live'")['n'] == 2
    from schoolguard.schemas import CameraView
    ledger = app.state.live_sessions[ident]['analyzer'].face_ledger
    ledger.body_faces[7] = {'id': next(iter(ledger.records)), 'last': 0}
    endpoint('/api/live/{ident}/view')(ident, CameraView(rotation=90, mirror=False), current)
    assert not ledger.body_faces
    assert all(r['last_bbox'] is None for r in ledger.records.values())
    assert app.state.db.one("SELECT count(*) n FROM faces WHERE kind='live'")['n'] == 2
    endpoint('/api/live/{ident}/stop')(ident, current)


def test_preview_continues_during_inference_and_rotation_is_serialized(tmp_path, monkeypatch):
    from concurrent.futures import ThreadPoolExecutor

    from fastapi import HTTPException

    from schoolguard.app import create_app
    from schoolguard.config import Settings
    from schoolguard.schemas import CameraView
    module = importlib.import_module('schoolguard.app')
    entered, release = threading.Event(), threading.Event()
    data = cv2.imencode('.jpg', np.zeros((120, 160, 3), np.uint8))[1].tobytes()
    class Source:
        def __init__(self, _url): pass
        def jpeg(self): return data
        def set_view(self, rotation, mirror): self.rotation, self.mirror = rotation, mirror
        def close(self): pass
    class Detector:
        resets = 0
        def __init__(self, *_args): pass
        def __call__(self, _frame):
            entered.set()
            assert release.wait(5)
            return []
        def reset_tracking(self): self.resets += 1
    monkeypatch.setattr(module, 'NetworkCamera', Source)
    app = create_app(Settings(runtime=tmp_path/'runtime', models=tmp_path/'models',
                             data_root=tmp_path/'data', start_worker=False), detector_factory=Detector)
    app.state.db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'test','x','operator')")
    app.state.db.execute(
        "INSERT INTO customer_profiles(user_id,display_name,email,phone,updated_at) VALUES(1,'Test','test@example.test','',?)",
        (now(),),
    )
    app.state.db.execute(
        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at) VALUES(1,'123456789',?)",
        (now(),),
    )
    app.state.db.execute(
        "INSERT INTO subscriptions(user_id,plan,expires_at,source,updated_at) VALUES(1,'pro_local',NULL,'test',?)",
        (now(),),
    )
    app.state.telegram_linker.token = 'test-token'
    def endpoint(path): return next(r.endpoint for r in app.routes if r.path == path)
    current = {'id': 1, 'username': 'test', 'role': 'operator'}
    ident = endpoint('/api/live/start')(JobRequest(source_id='live', camera_url='http://192.168.1.2/live.flv'), current)['id']
    with ThreadPoolExecutor(max_workers=3) as pool:
        inference = pool.submit(endpoint('/api/live/{ident}/remote-frame'), ident, current)
        try:
            assert entered.wait(2)
            response = pool.submit(endpoint('/api/live/{ident}/preview'), ident, current).result(timeout=1)
            assert response.body == data
            assert response.headers['cache-control'] == 'no-store'
            view = pool.submit(endpoint('/api/live/{ident}/view'), ident, CameraView(rotation=90), current)
            assert not view.done()
        finally:
            release.set()
        assert inference.result(timeout=2)['people'] == 0
        assert view.result(timeout=2) == {'rotation': 90, 'mirror': False}
    session = app.state.live_sessions[ident]
    assert session['analyzer'].detector.resets == 1
    assert session['source'].rotation == 90
    for path, args in [('/api/live/{ident}/preview', []), ('/api/live/{ident}/view', [CameraView()])]:
        with pytest.raises(HTTPException) as exc:
            endpoint(path)(ident, *args, {'id': 2, 'role': 'operator'})
        assert exc.value.status_code == 403
    app.state.db.execute("UPDATE subscriptions SET plan='free' WHERE user_id=1")
    with pytest.raises(HTTPException) as exc:
        endpoint('/api/live/{ident}/preview')(ident, current)
    assert exc.value.status_code == 403
    endpoint('/api/live/{ident}/stop')(ident, current)
    with pytest.raises(HTTPException) as exc:
        endpoint('/api/live/{ident}/preview')(ident, current)
    assert exc.value.status_code == 404


def test_standard_model_counts_people_and_objects_in_one_pass(tmp_path, monkeypatch):
    from schoolguard.app import create_app
    from schoolguard.config import Settings
    module = importlib.import_module('schoolguard.app')
    created = []
    class Detector:
        def __init__(self, _settings, _config, classes=None):
            self.classes = classes
            created.append(self)
        def __call__(self, _frame):
            return [{'class_id': label, 'label': 'person' if label == 0 else 'car',
                     'track_id': i, 'confidence': .9, 'bbox': [i*.3, .1, i*.3+.2, .8]}
                    for i, label in enumerate([0, 0, 2]) if label in self.classes]
    monkeypatch.setattr(module, 'PersonDetector', Detector)
    settings = Settings(runtime=tmp_path/'runtime', models=tmp_path/'models', data_root=tmp_path/'data', start_worker=False)
    settings.models.mkdir(parents=True)
    (settings.models/'yolo11s.pt').touch()
    app = create_app(settings)
    app.state.db.execute("INSERT INTO users(id,username,password,role) VALUES(1,'admin','x','admin')")
    start = next(r.endpoint for r in app.routes if r.path == '/api/live/start')
    ident = start(JobRequest(source_id='live', model='yolo11s', detect_objects=True), {'id': 1, 'username': 'admin', 'role': 'admin'})['id']
    analyzer = app.state.live_sessions[ident]['analyzer']
    assert len(created) == 1
    assert analyzer.object_detector is None
    result = analyzer.update(cv2.imencode('.jpg', np.zeros((120, 160, 3), np.uint8))[1].tobytes())
    assert result['people'] == 2 and result['objects'] == 1
