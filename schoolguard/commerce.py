"""Opt-in commerce adapters. No real payment call occurs without explicit configuration."""

import hashlib
import hmac
import ipaddress
import json
import os
import smtplib
import ssl
from contextlib import contextmanager
from email.message import EmailMessage
from urllib.parse import urlparse

import requests


def hash_email_token(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def valid_public_url(value):
    parsed = urlparse(value)
    try:
        ipaddress.ip_address(parsed.hostname or "")
        is_ip = True
    except ValueError:
        is_ip = False
    try:
        port = parsed.port
    except ValueError:
        return False
    return (parsed.scheme == "https" and bool(parsed.hostname)
            and not is_ip and parsed.hostname != "localhost"
            and port in (None, 443)
            and not parsed.hostname.endswith(".trycloudflare.com")
            and not parsed.hostname.endswith((".example", ".test", ".invalid", ".localhost"))
            and not parsed.username and not parsed.password and not parsed.path.rstrip("/")
            and not parsed.query and not parsed.fragment)


class SmtpEmailSender:
    def __init__(self):
        self.host = os.environ.get("SMTP_HOST", "")
        self.port = int(os.environ.get("SMTP_PORT", "587"))
        self.username = os.environ.get("SMTP_USER", "")
        self.password = os.environ.get("SMTP_PASSWORD", "")
        self.sender = os.environ.get("SMTP_FROM", "")
        self.available = all((self.host, self.username, self.password, self.sender))

    def send_verification(self, recipient, url):
        self._send(recipient, "Xác minh email LH25",
                   "Mở liên kết sau để xác minh email LH25 (có hiệu lực 30 phút):\n"
                   f"{url}\n\nNếu bạn không tạo tài khoản, hãy bỏ qua thư này.")

    def send_payment_confirmation(self, recipient, message):
        self._send(recipient, "LH25 · Xác nhận thanh toán Pro", message)

    def _send(self, recipient, subject, content):
        if not self.available:
            raise RuntimeError("Email chưa được cấu hình.")
        message = EmailMessage()
        message["From"] = self.sender
        message["To"] = recipient
        message["Subject"] = subject
        message.set_content(content)
        with self._connection() as server:
            server.send_message(message)

    def check_connection(self):
        """Verify TLS and SMTP login without sending any message."""
        with self._connection():
            return True

    @contextmanager
    def _connection(self):
        if not self.available:
            raise RuntimeError("Email chưa được cấu hình.")
        context = ssl.create_default_context()
        if self.port == 465:
            with smtplib.SMTP_SSL(self.host, self.port, timeout=12, context=context) as server:
                server.login(self.username, self.password)
                yield server
        else:
            with smtplib.SMTP(self.host, self.port, timeout=12) as server:
                server.ehlo()
                server.starttls(context=context)
                server.ehlo()
                server.login(self.username, self.password)
                yield server


def _signature_value(value):
    if value is None or value in ("null", "undefined"):
        return ""
    if isinstance(value, list):
        return json.dumps([dict(sorted(item.items())) for item in value],
                          ensure_ascii=False, separators=(",", ":"))
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def payos_signature(data, checksum_key):
    payload = "&".join(f"{key}={_signature_value(value)}" for key, value in sorted(data.items()))
    return hmac.new(checksum_key.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class PayOSGateway:
    API_URL = "https://api-merchant.payos.vn/v2/payment-requests"

    def __init__(self):
        self.client_id = os.environ.get("LH25_PAYOS_CLIENT_ID", "")
        self.api_key = os.environ.get("LH25_PAYOS_API_KEY", "")
        self.checksum_key = os.environ.get("LH25_PAYOS_CHECKSUM_KEY", "")
        self.available = all((self.client_id, self.api_key, self.checksum_key))

    def create_checkout(self, order_code, amount, base_url, *, local_pilot=False):
        if not self.available:
            raise RuntimeError("payOS chưa được cấu hình.")
        if not valid_public_url(base_url) and not (
            local_pilot and base_url == "http://localhost:8770"
        ):
            raise RuntimeError("Cần tên miền HTTPS cố định trước khi mở thanh toán.")
        signed = {
            "amount": amount,
            "cancelUrl": base_url + "/payment-cancel",
            "description": "LH25" + str(order_code)[-5:],
            "orderCode": order_code,
            "returnUrl": base_url + "/payment-return",
        }
        body = {**signed, "signature": payos_signature(signed, self.checksum_key)}
        response = requests.post(
            self.API_URL, json=body,
            headers={"x-client-id": self.client_id, "x-api-key": self.api_key},
            timeout=12, allow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()
        data = result.get("data")
        if result.get("code") != "00" or not isinstance(data, dict):
            raise RuntimeError("payOS không tạo được liên kết thanh toán.")
        signature = result.get("signature", "")
        if not hmac.compare_digest(payos_signature(data, self.checksum_key), signature):
            raise RuntimeError("Phản hồi payOS không có chữ ký hợp lệ.")
        url = str(data.get("checkoutUrl", ""))
        parsed = urlparse(url)
        if (parsed.scheme != "https" or parsed.hostname != "pay.payos.vn"
                or parsed.username or parsed.password or data.get("orderCode") != order_code
                or data.get("amount") != amount or not data.get("paymentLinkId")):
            raise RuntimeError("Phản hồi payOS không khớp đơn hàng.")
        return {"checkout_url": url, "payment_link_id": str(data["paymentLinkId"])}

    def verify_webhook(self, payload):
        if not self.available:
            return False
        data = payload.get("data") if isinstance(payload, dict) else None
        signature = payload.get("signature", "") if isinstance(payload, dict) else ""
        return (isinstance(data, dict) and isinstance(signature, str)
                and hmac.compare_digest(payos_signature(data, self.checksum_key), signature))

    def register_webhook(self, base_url):
        if not self.available or not valid_public_url(base_url):
            raise RuntimeError("Cần đủ khóa payOS và URL HTTPS cố định để đăng ký webhook.")
        webhook_url = base_url.rstrip("/") + "/api/payments/payos/webhook"
        response = requests.post(
            "https://api-merchant.payos.vn/confirm-webhook",
            headers={"x-client-id": self.client_id, "x-api-key": self.api_key},
            json={"webhookUrl": webhook_url}, timeout=(5, 20), allow_redirects=False,
        )
        response.raise_for_status()
        result = response.json()
        data = result.get("data")
        if (result.get("code") != "00" or not isinstance(data, dict)
                or data.get("webhookUrl") != webhook_url):
            raise RuntimeError("payOS chưa xác nhận webhook đã đăng ký.")
        return webhook_url
