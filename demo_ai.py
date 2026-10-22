import os
import tempfile

import cv2
import requests

BASE_URL = os.getenv("SCHOOLGUARD_API_URL", "http://127.0.0.1:8000")
API_URL = f"{BASE_URL}/api/alerts"
USERNAME = os.getenv("SCHOOLGUARD_ADMIN_USER", "admin")
PASSWORD = os.getenv("SCHOOLGUARD_ADMIN_PASSWORD")

if not PASSWORD:
    raise SystemExit("Hãy đặt SCHOOLGUARD_ADMIN_PASSWORD trước khi chạy demo_ai.py")


def get_access_token():
    response = requests.post(
        f"{BASE_URL}/token",
        data={"username": USERNAME, "password": PASSWORD},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()["access_token"]


try:
    access_token = get_access_token()
except requests.RequestException as exc:
    raise SystemExit(f"Không đăng nhập được Backend: {exc}") from exc

cap = cv2.VideoCapture(0)
print("🎥 Đã bật Camera mô phỏng AI.")
print("👉 Nhấn SPACE để giả lập phát hiện xâm nhập; nhấn Q để thoát.")

try:
    while True:
        ret, frame = cap.read()
        if not ret:
            print("Không đọc được hình ảnh từ webcam.")
            break

        cv2.rectangle(frame, (100, 100), (500, 400), (0, 0, 255), 2)
        cv2.putText(
            frame,
            "KHU VUC CAM (ZONE 1)",
            (110, 130),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 0, 255),
            2,
        )
        cv2.imshow("SchoolGuard AI - Camera Bai Xe", frame)

        key = cv2.waitKey(1) & 0xFF
        if key == 32:
            print("🚨 Đang gửi cảnh báo về Backend...")
            with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as image_file:
                temp_img = image_file.name
            try:
                if not cv2.imwrite(temp_img, frame):
                    raise RuntimeError("Không lưu được ảnh cảnh báo")
                with open(temp_img, "rb") as image_data:
                    response = requests.post(
                        API_URL,
                        data={"camera_id": "CAM-01", "zone_name": "Khu vực để xe giáo viên"},
                        files={"file": ("alert.jpg", image_data, "image/jpeg")},
                        headers={"Authorization": f"Bearer {access_token}"},
                        timeout=30,
                    )
                response.raise_for_status()
                print("✅ Gửi thành công! Hãy xem giao diện Web.")
            except (requests.RequestException, RuntimeError) as exc:
                print(f"❌ Không gửi được cảnh báo: {exc}")
            finally:
                if os.path.exists(temp_img):
                    os.remove(temp_img)
        elif key == ord("q"):
            break
finally:
    cap.release()
    cv2.destroyAllWindows()
