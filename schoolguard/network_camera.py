"""Bounded network-camera reader; only explicitly entered private LAN IPs."""

import ipaddress
import threading
import time
from urllib.parse import quote, unquote, urlsplit, urlunsplit

import cv2
import requests


def camera_credentials(url, username='', password=''):
    validate_camera_url(url)
    parsed = urlsplit(url)
    if not username and not password:
        return url
    host = parsed.hostname
    if ':' in host:
        host = '[' + host + ']'
    if parsed.port:
        host += ':' + str(parsed.port)
    netloc = quote(username, safe='') + ':' + quote(password, safe='') + '@' + host
    return urlunsplit(parsed._replace(netloc=netloc))


def probe_camera(url):
    """Read HTTP status without consuming or saving the video stream."""
    parsed = urlsplit(url)
    if parsed.scheme not in {'http', 'https'}:
        return
    clean = urlunsplit(parsed._replace(netloc=parsed.netloc.rsplit('@', 1)[-1]))
    auth = ((unquote(parsed.username or ''), unquote(parsed.password or ''))
            if parsed.username is not None else None)
    try:
        with requests.Session() as session:
            session.trust_env = False
            with session.get(clean, auth=auth, stream=True, timeout=(5, 5),
                             allow_redirects=False) as response:
                if response.status_code in {401, 403}:
                    raise ValueError('Camera yêu cầu đăng nhập hoặc tài khoản không đúng. Điền Tài khoản camera và Mật khẩu camera trong SchoolGuard; đây không phải tài khoản admin của web.')
                if response.status_code == 404:
                    raise ValueError('Không tìm thấy luồng video (HTTP 404). Kiểm tra đường dẫn, ví dụ /live.flv của IP Camera Lite.')
                if 300 <= response.status_code < 400:
                    raise ValueError('Camera chuyển hướng sang địa chỉ khác. Nhập trực tiếp URL luồng video.')
                if response.status_code >= 400:
                    raise ValueError(f'Camera trả lỗi HTTP {response.status_code}. Kiểm tra app camera.')
                if 'text/html' in response.headers.get('Content-Type', '').lower():
                    raise ValueError('Đây là trang xem camera, chưa phải luồng video. Với IP Camera Lite, nhập URL kết thúc bằng /live.flv.')
    except requests.RequestException as exc:
        raise ValueError('Không truy cập được camera. Giữ app iPhone mở và kiểm tra hai thiết bị cùng mạng Wi-Fi.') from exc


def validate_camera_url(value):
    try:
        url = urlsplit(value)
        address = ipaddress.ip_address(url.hostname or '')
        if (url.scheme not in {'rtsp', 'http', 'https'} or not address.is_private
                or address.is_loopback or address.is_link_local or address.is_multicast
                or address.is_unspecified or url.fragment or not url.port and value.endswith(':')):
            raise ValueError
        # Validate malformed/out-of-range ports, even when omitted in normal URLs.
        _ = url.port
    except ValueError as exc:
        raise ValueError('Nhập URL RTSP/HTTP(S) với địa chỉ IP riêng trong mạng LAN, ví dụ http://192.168.1.20:8080/video.') from exc
    return value


class NetworkCamera:
    def __init__(self, url):
        validate_camera_url(url)
        probe_camera(url)
        self.rotation = 0
        self.mirror = False
        self.condition = threading.Condition()
        self.stopped = threading.Event()
        self.latest = None
        self.received_at = 0.0
        self.failed = False
        self.capture = cv2.VideoCapture(url, cv2.CAP_FFMPEG, [
            cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
            cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
        ])
        if not self.capture.isOpened():
            self.capture.release()
            raise ValueError('Không kết nối được camera. Kiểm tra IP, cổng, đường dẫn, tài khoản và kết nối mạng.')
        self.capture.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        # One reader continuously drains the decoder. Inference consumes only
        # the newest frame; slow clients cannot build a FIFO of old video.
        self.reader = threading.Thread(target=self._read_latest, daemon=True,
                                       name='network-camera-reader')
        self.reader.start()

    def _read_latest(self):
        try:
            while not self.stopped.is_set():
                ok, frame = self.capture.read()
                with self.condition:
                    if not ok or frame is None:
                        self.failed = True
                        self.condition.notify_all()
                        return
                    self.latest = frame
                    self.received_at = time.monotonic()
                    self.condition.notify_all()
        except cv2.error:
            with self.condition:
                self.failed = True
                self.condition.notify_all()
        finally:
            self.capture.release()

    def jpeg(self):
        with self.condition:
            self.condition.wait_for(lambda: self.latest is not None or self.failed
                                    or self.stopped.is_set(), timeout=6)
            if (self.latest is None or self.failed or self.stopped.is_set()
                    or time.monotonic() - self.received_at > 2):
                raise ValueError('Camera mất tín hiệu hoặc ảnh đã cũ. Kiểm tra thiết bị rồi kết nối lại.')
            frame = self.latest
            rotation, mirror = self.rotation, self.mirror
        rotations = {90: cv2.ROTATE_90_CLOCKWISE, 180: cv2.ROTATE_180,
                     270: cv2.ROTATE_90_COUNTERCLOCKWISE}
        if rotation in rotations:
            frame = cv2.rotate(frame, rotations[rotation])
        if mirror:
            frame = cv2.flip(frame, 1)
        h, w = frame.shape[:2]
        # Preserve equal detail in portrait and landscape instead of limiting
        # portrait frames to 720px high (which previously shrank distant faces).
        scale = min(1., 1280/max(w, h))
        if scale < 1:
            frame = cv2.resize(frame, (round(w*scale), round(h*scale)))
        ok, data = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        if not ok:
            raise ValueError('Không đọc được ảnh camera.')
        return data.tobytes()

    def set_view(self, rotation, mirror):
        with self.condition:
            self.rotation, self.mirror = rotation, mirror

    def close(self):
        self.stopped.set()
        with self.condition:
            self.condition.notify_all()
        self.reader.join(timeout=6)
