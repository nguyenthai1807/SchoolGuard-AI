import hashlib
import math
from pathlib import Path

import cv2


def index_dataset(db, root):
    if not root.is_dir():
        return 0
    items = []
    for path in sorted((root / "training/videos").glob("*.avi")):
        items.append((path, "video", "training"))
    for path in sorted((root / "testing/frames").glob("*")):
        if path.is_dir() and next(path.glob("*.jpg"), None):
            items.append((path, "frames", "testing"))
    with db.connect() as conn:
        for path, kind, split in items:
            key = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
            conn.execute(
                "INSERT OR IGNORE INTO sources VALUES(?,?,?,?,?)",
                (key, path.name, str(path.resolve()), kind, split),
            )
    return len(items)


class Reader:
    def __init__(self, path, kind="video", fps=25):
        self.cap = None
        self.files = None
        self.index = 0
        if kind == "frames":
            self.files = sorted(Path(path).glob("*.jpg"))
            if not self.files:
                raise ValueError("Thư mục không có ảnh JPG.")
            first = cv2.imread(str(self.files[0]))
            if first is None:
                raise ValueError("Không đọc được ảnh đầu tiên.")
            self.height, self.width = first.shape[:2]
            self.count, self.fps = len(self.files), fps
        else:
            self.cap = cv2.VideoCapture(str(path))
            if not self.cap.isOpened():
                self.close()
                raise ValueError("Không mở được video.")
            self.count = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)
            self.width = int(self.cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            self.height = int(self.cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if (
            not math.isfinite(self.fps)
            or self.fps <= 0
            or self.count <= 0
            or not (0 < self.width <= 7680 and 0 < self.height <= 4320)
        ):
            self.close()
            raise ValueError("FPS, số frame hoặc kích thước video không hợp lệ.")

    def read(self):
        if self.index >= self.count:
            return None
        if self.files is not None:
            frame = cv2.imread(str(self.files[self.index]))
        else:
            ok, frame = self.cap.read()
            if not ok:
                frame = None
        if frame is None:
            raise ValueError(f"Lỗi giải mã frame {self.index}/{self.count}.")
        if frame.shape[:2] != (self.height, self.width):
            raise ValueError("Kích thước frame thay đổi giữa clip.")
        self.index += 1
        return frame

    def close(self):
        if self.cap is not None:
            self.cap.release()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def metadata(source):
    with Reader(source["path"], source["kind"]) as reader:
        return {
            "width": reader.width,
            "height": reader.height,
            "frames": reader.count,
            "fps": reader.fps,
            "duration": reader.count / reader.fps,
            "fps_assumed": source["kind"] == "frames",
        }


def jpeg(frame):
    ok, data = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
    if not ok:
        raise ValueError("Không mã hóa được ảnh.")
    return data.tobytes()
