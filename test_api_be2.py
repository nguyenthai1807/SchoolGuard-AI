"""Manual end-to-end API check for the BE2 authentication and alert flow."""

import getpass
import os
import time

import cv2
import numpy as np
import requests


BASE_URL = os.getenv("SCHOOLGUARD_API_URL", "http://127.0.0.1:8000").rstrip("/")
EXPECTED_ALERT_FIELDS = {
    "id",
    "camera_id",
    "zone_name",
    "location",
    "timestamp",
    "image_url",
    "evidence_image_url",
    "status",
}


def timed_request(label, method, url, **kwargs):
    started = time.perf_counter()
    response = requests.request(method, url, timeout=15, **kwargs)
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"{label}: HTTP {response.status_code}, {elapsed_ms:.1f} ms")
    return response


def fail(message):
    print(f"FAIL: {message}")
    raise SystemExit(1)


def main():
    username = os.getenv("SCHOOLGUARD_ADMIN_USER") or input("Tài khoản [admin]: ").strip() or "admin"
    password = os.getenv("SCHOOLGUARD_ADMIN_PASSWORD") or getpass.getpass("Mật khẩu: ")

    try:
        bad_login = timed_request(
            "Đăng nhập sai (kỳ vọng 401)", "POST", f"{BASE_URL}/token",
            data={"username": username, "password": password + "__invalid__"},
        )
        if bad_login.status_code != 401:
            fail(f"Đăng nhập sai phải trả 401, nhận {bad_login.status_code}")

        login = timed_request(
            "Đăng nhập đúng", "POST", f"{BASE_URL}/token",
            data={"username": username, "password": password},
        )
        if login.status_code != 200:
            fail(f"Không lấy được token: {login.text[:300]}")
        token = login.json().get("access_token")
        if not token:
            fail("API trả HTTP 200 nhưng không có access_token")
        print("PASS: token được cấp; token không in ra màn hình.")

        headers = {"Authorization": f"Bearer {token}"}
        pixels = np.full((240, 400, 3), (40, 120, 220), dtype=np.uint8)
        cv2.putText(pixels, "BE2 API TEST", (30, 125), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        encoded_ok, encoded_image = cv2.imencode(".jpg", pixels)
        if not encoded_ok:
            fail("Không tạo được ảnh kiểm thử JPEG")

        created = timed_request(
            "Tạo cảnh báo giả", "POST", f"{BASE_URL}/api/alerts",
            headers=headers,
            data={"camera_id": "TEST-BE2", "zone_name": "Vùng thử nghiệm API"},
            files={"file": ("be2-test.jpg", encoded_image.tobytes(), "image/jpeg")},
        )
        if created.status_code != 201:
            fail(f"Không lưu được cảnh báo: {created.text[:300]}")
        alert = created.json()
        missing_fields = EXPECTED_ALERT_FIELDS - alert.keys()
        if missing_fields:
            fail(f"Response tạo cảnh báo thiếu trường: {', '.join(sorted(missing_fields))}")
        alert_id = alert["id"]
        print(f"PASS: cảnh báo #{alert_id} đã lưu; timestamp={alert['timestamp']}, vị trí={alert['location']}.")

        listed = timed_request(
            "Đọc danh sách cảnh báo", "GET", f"{BASE_URL}/api/alerts",
            headers=headers, params={"limit": 100},
        )
        if listed.status_code != 200:
            fail(f"Không đọc được danh sách: {listed.text[:300]}")
        row = next((item for item in listed.json() if item.get("id") == alert_id), None)
        if row is None:
            fail("Cảnh báo vừa tạo chưa xuất hiện trong GET /api/alerts")
        missing_fields = EXPECTED_ALERT_FIELDS - row.keys()
        if missing_fields or not row.get("timestamp") or not row.get("location") or not row.get("status"):
            fail(f"Cảnh báo trong danh sách thiếu dữ liệu: {', '.join(sorted(missing_fields)) or 'giá trị rỗng'}")
        print("PASS: DB/API trả lại đủ thời gian, vị trí, ảnh minh chứng, camera và trạng thái.")

        image = timed_request(
            "Tải ảnh minh chứng", "GET", f"{BASE_URL}{row['evidence_image_url']}", headers=headers,
        )
        if image.status_code != 200 or not image.content or not image.headers.get("content-type", "").startswith("image/"):
            fail("Ảnh minh chứng không tải được hoặc content-type không phải ảnh")
        print(f"PASS: ảnh minh chứng tải được ({len(image.content)} bytes).")

        updated = timed_request(
            "Cập nhật trạng thái", "PUT", f"{BASE_URL}/api/alerts/{alert_id}/status",
            headers=headers, json={"status": "Đang xử lý"},
        )
        if updated.status_code != 200 or updated.json().get("status") != "Đang xử lý":
            fail(f"Không cập nhật được trạng thái: {updated.text[:300]}")
        print(f"PASS: trạng thái cảnh báo #{alert_id} đã đổi thành 'Đang xử lý'.")
        print("Hoàn tất. Bản ghi TEST-BE2 được giữ trong database để kiểm tra trên giao diện.")
    except requests.RequestException as error:
        fail(f"Không kết nối được {BASE_URL}: {error}. Hãy kiểm tra backend và cổng 8000.")


if __name__ == "__main__":
    main()
