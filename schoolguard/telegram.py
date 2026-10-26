"""Best-effort Telegram delivery for locally confirmed alert episodes.

The bot token and destination are read from the environment, never persisted in
SQLite or returned by the API. A failed delivery cannot turn a completed video
analysis into a failed job.
"""

import logging
import os

import requests

log = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, token=None, chat_id=None, session=None):
        self.token = token if token is not None else os.getenv("LH25_TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id if chat_id is not None else os.getenv("LH25_TELEGRAM_CHAT_ID", "")
        self.session = session or requests.Session()

    @property
    def configured(self):
        return bool(self.token and self.chat_id)

    def send_text(self, message):
        """Verify that this bot can actually deliver to the selected private chat."""
        if not self.configured:
            return False
        try:
            response = self.session.post(
                f"https://api.telegram.org/bot{self.token}/sendMessage",
                data={"chat_id": self.chat_id, "text": message}, timeout=(5, 10),
            )
            response.raise_for_status()
            return response.json().get("ok") is True
        except (requests.RequestException, ValueError):
            log.warning("Telegram confirmation delivery failed")
            return False

    def send(self, alert, evidence, source_name, timestamp):
        """Return (delivered, diagnostic); do not expose credentials in errors."""
        if not self.configured:
            return False, "telegram_not_configured"
        event = alert.get("event_type", "restricted_zone")
        count = alert.get("details", {}).get("count")
        message = (
            f"🚨 LH25 · {alert.get('zone', event)}\n"
            f"Nguồn: {source_name}\n"
            f"Mốc: {timestamp:.1f} giây\n"
            f"Loại: {event}"
        )
        if count is not None:
            message += f"\nSố người quan sát: {count}"
        message += "\nCần xem ảnh/video để xác minh; AI có thể báo sai hoặc bỏ sót."
        try:
            response = self.session.post(
                f"https://api.telegram.org/bot{self.token}/sendPhoto",
                data={"chat_id": self.chat_id, "caption": message[:1024]},
                files={"photo": ("evidence.jpg", evidence, "image/jpeg")},
                timeout=(5, 10),
            )
            response.raise_for_status()
            if response.json().get("ok") is not True:
                return False, "telegram_rejected"
            return True, "delivered"
        except (requests.RequestException, ValueError):
            log.warning("Telegram delivery failed for %s", event)
            return False, "telegram_delivery_failed"
