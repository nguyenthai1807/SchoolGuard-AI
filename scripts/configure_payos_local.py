"""One-use, loopback-only form for importing payOS keys or Gmail SMTP settings.

The UI bridge keeps values out of command arguments and tool output. It never
enables payments or creates payment links. Only the selected settings change.
"""

import argparse
import html
import os
import re
import secrets
import shutil
import tempfile
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs

KEYS = ("LH25_PAYOS_CLIENT_ID", "LH25_PAYOS_API_KEY", "LH25_PAYOS_CHECKSUM_KEY")
EMAIL_KEYS = ("SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASSWORD", "SMTP_FROM")
ROOT = Path(__file__).resolve().parents[1]


def save_keys(values, root=ROOT):
    if set(values) != set(KEYS) or any(not re.fullmatch(r"[A-Za-z0-9_-]{16,256}", value)
                                       for value in values.values()):
        raise ValueError("Three valid channel keys are required.")
    _save_env(values, root)


def save_gmail(values, root=ROOT):
    if set(values) != set(EMAIL_KEYS):
        raise ValueError("Incomplete SMTP settings.")
    values = dict(values)
    if (values["SMTP_HOST"] != "smtp.gmail.com" or values["SMTP_PORT"] != "465"
            or not re.fullmatch(r"[A-Za-z0-9._%+-]+@gmail\.com", values["SMTP_USER"])
            or values["SMTP_FROM"] != values["SMTP_USER"]):
        raise ValueError("Use the authenticated Gmail sender and TLS port 465.")
    password = values["SMTP_PASSWORD"].replace(" ", "")
    if not re.fullmatch(r"[a-zA-Z0-9]{16}", password):
        raise ValueError("A Google app password is required.")
    values["SMTP_PASSWORD"] = password
    _save_env(values, root)


def _save_env(values, root):
    target = root / ".env"
    old = target.read_text(encoding="utf-8-sig").splitlines() if target.is_file() else []
    result, seen = [], set()
    for line in old:
        key = line.split("=", 1)[0].strip() if "=" in line and not line.lstrip().startswith("#") else ""
        if key in values:
            if key not in seen:
                result.append(f"{key}={values[key]}")
                seen.add(key)
        else:
            result.append(line)
    result.extend(f"{key}={values[key]}" for key in values if key not in seen)
    if target.is_file():
        backups = root / "runtime/backups"
        backups.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target, backups / f"env-payos-{secrets.token_hex(12)}.txt")
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", prefix=".env-", suffix=".tmp",
                                         dir=root, delete=False) as stream:
            temporary = Path(stream.name)
            stream.write("\n".join(result) + "\n")
        os.replace(temporary, target)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", action="store_true", help="Import Gmail SMTP app password instead of payOS keys")
    args = parser.parse_args()
    fields_keys = EMAIL_KEYS if args.email else KEYS
    heading = "Cấu hình email LH25 trên máy" if args.email else "Cấu hình payOS LH25 trên máy"
    success = "Đã lưu cấu hình email vào LH25" if args.email else "Đã lưu đủ 3 khóa payOS vào LH25"
    origin = "http://127.0.0.1:8772"
    setup_path = "/setup/" + secrets.token_urlsafe(24)
    saved = False

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # No request or credential logging.

        def respond(self, status, body):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
            self.send_header("Content-Security-Policy", "default-src 'none'; form-action 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path != setup_path or self.headers.get("Host") != "127.0.0.1:8772":
                self.respond(404, "Not found")
                return
            fields = "".join(f'<p><label>{html.escape(key)}<input name="{key}" type="password" required autocomplete="off"></label></p>' for key in fields_keys)
            self.respond(200, '<!doctype html><meta charset="utf-8"><title>Cấu hình payOS LH25</title>'
                         f'<h1>{heading}</h1><p>Chỉ lưu cấu hình trên máy; chưa bật thu tiền.</p>'
                         f'<form method="POST" action="{setup_path}">{fields}<button type="submit">Lưu khóa vào LH25</button></form>')

        def do_POST(self):
            nonlocal saved
            same_origin = self.headers.get("Origin") == origin or (
                self.headers.get("Origin") == "null" and self.headers.get("Sec-Fetch-Site") == "same-origin")
            if (self.path != setup_path or not same_origin
                    or self.headers.get("Host") != "127.0.0.1:8772" or saved):
                self.respond(403, "Forbidden")
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError
                submitted = parse_qs(self.rfile.read(size).decode("utf-8"), strict_parsing=True)
                if any(len(values) != 1 for values in submitted.values()):
                    raise ValueError
                (save_gmail if args.email else save_keys)({key: values[0] for key, values in submitted.items()})
            except Exception:
                self.respond(400, "Không lưu được cấu hình. Không hiển thị giá trị khóa.")
                return
            saved = True
            self.respond(200, '<!doctype html><meta charset="utf-8"><title>LH25 · Đã lưu cấu hình</title>'
                         f'<h1>{success}</h1><p>Khóa được giữ trên máy. Thanh toán thật chưa được bật.</p>')

    with HTTPServer(("127.0.0.1", 8772), Handler) as server:
        server.timeout = 1
        print("SETUP_URL " + origin + setup_path, flush=True)
        expires = time.monotonic() + 600
        while not saved and time.monotonic() < expires:
            server.handle_request()
    print("KEYS_SAVED" if saved else "SETUP_EXPIRED", flush=True)


if __name__ == "__main__":
    main()
