"""Pair a local LH25 account with a private Telegram chat.

This single-process polling flow is for the local pilot. Production should use a
verified webhook and a durable queue, not competing getUpdates consumers.
"""

import hashlib
import logging
import re
import secrets
import threading
import time

import requests

from .db import now
from .telegram import TelegramNotifier

log = logging.getLogger(__name__)
BOT_NAME = re.compile(r"^[A-Za-z0-9_]{5,32}$")
START_CODE = re.compile(r"^/start(?:@[A-Za-z0-9_]+)?\s+([A-Za-z0-9_-]{20,64})\s*$")


class TelegramUnavailable(Exception):
    pass


class TelegramLinker:
    def __init__(self, db, token, session=None):
        self.db = db
        self.token = token
        self.session = session or requests.Session()
        self.lock = threading.Lock()

    def status(self, user_id):
        row = self.db.one("SELECT chat_id,verified_at,telegram_username FROM telegram_accounts WHERE user_id=?",
                          (user_id,))
        pending = self.db.one("SELECT user_id FROM telegram_pending WHERE user_id=? AND expires>?",
                              (user_id, time.time()))
        return {
            "bot_configured": bool(self.token),
            "linked": bool(row),
            "pairing_pending": bool(pending),
            "chat_hint": ("…" + row["chat_id"][-4:]) if row else None,
            "telegram_username": (row["telegram_username"] or None) if row else None,
            "verified_at": row["verified_at"] if row else None,
        }

    def _get(self, method, params=None):
        if not self.token:
            raise TelegramUnavailable("Bot Telegram chưa được quản trị viên cấu hình.")
        try:
            response = self.session.get(
                f"https://api.telegram.org/bot{self.token}/{method}",
                params=params, timeout=(5, 10),
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("ok") is not True:
                raise TelegramUnavailable("Telegram từ chối yêu cầu; kiểm tra cấu hình bot.")
            return payload.get("result")
        except (requests.RequestException, ValueError) as exc:
            log.warning("Telegram pairing request failed: %s", method)
            raise TelegramUnavailable("Không kết nối được Telegram. Hãy thử lại sau.") from exc

    def begin(self, user_id):
        bot = self._get("getMe")
        name = bot.get("username") if isinstance(bot, dict) else None
        if not name or not BOT_NAME.fullmatch(name):
            raise TelegramUnavailable("Không xác định được tên bot Telegram.")
        code = secrets.token_urlsafe(24)
        digest = hashlib.sha256(code.encode()).hexdigest()
        expires = time.time() + 600
        with self.db.connect() as conn:
            conn.execute("DELETE FROM telegram_pending WHERE user_id=?", (user_id,))
            conn.execute(
                "INSERT INTO telegram_pending(user_id,code_hash,expires) VALUES(?,?,?)",
                (user_id, digest, expires),
            )
        return {"url": f"https://t.me/{name}?start={code}",
                "command": f"/start {code}", "expires_in_seconds": 600}

    def check(self, user_id):
        if not self.token:
            raise TelegramUnavailable("Bot Telegram chưa được quản trị viên cấu hình.")
        with self.lock:
            offset = self.db.one("SELECT next_offset FROM telegram_poll WHERE id=1")["next_offset"]
            updates = self._get("getUpdates", {"offset": offset, "limit": 100, "timeout": 0})
            if not isinstance(updates, list):
                raise TelegramUnavailable("Phản hồi Telegram không hợp lệ.")
            for update in updates:
                try:
                    update_id = int(update["update_id"])
                    message = update.get("message") or {}
                    chat = message.get("chat") or {}
                    match = START_CODE.fullmatch(message.get("text", ""))
                    if (match and chat.get("type") == "private" and
                            str(chat.get("id")) == str((message.get("from") or {}).get("id"))):
                        digest = hashlib.sha256(match.group(1).encode()).hexdigest()
                        pending = self.db.one(
                            "SELECT user_id FROM telegram_pending WHERE code_hash=? AND expires>?",
                            (digest, time.time()),
                        )
                        if pending:
                            chat_id = str(chat["id"])
                            existing = self.db.one(
                                "SELECT user_id FROM telegram_accounts WHERE chat_id=?",
                                (chat_id,),
                            )
                            if existing and existing["user_id"] != pending["user_id"]:
                                log.warning("Telegram chat is already paired with another account")
                                offset = max(offset, update_id + 1)
                                continue
                            sender = TelegramNotifier(token=self.token, chat_id=chat_id,
                                                      session=self.session)
                            if sender.send_text("LH25: Kết nối cảnh báo thành công."):
                                username = (message.get("from") or {}).get("username", "")
                                username = username if BOT_NAME.fullmatch(username) else ""
                                with self.db.connect() as conn:
                                    conn.execute(
                                        "INSERT INTO telegram_accounts(user_id,chat_id,verified_at,telegram_username) "
                                        "VALUES(?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET "
                                        "chat_id=excluded.chat_id,verified_at=excluded.verified_at,"
                                        "telegram_username=excluded.telegram_username",
                                        (pending["user_id"], chat_id, now(), username),
                                    )
                                    conn.execute("DELETE FROM telegram_pending WHERE user_id=?",
                                                 (pending["user_id"],))
                    if update_id >= offset:
                        offset = update_id + 1
                except (KeyError, TypeError, ValueError):
                    log.warning("Ignored malformed Telegram update")
            self.db.execute("UPDATE telegram_poll SET next_offset=? WHERE id=1", (offset,))
        return self.status(user_id)

    def disconnect(self, user_id):
        with self.db.connect() as conn:
            conn.execute("DELETE FROM telegram_pending WHERE user_id=?", (user_id,))
            conn.execute("DELETE FROM telegram_accounts WHERE user_id=?", (user_id,))


def recipient_for(db, user_id, notifier):
    """Never send another user's event to the legacy shared chat destination."""
    account = db.one("SELECT chat_id FROM telegram_accounts WHERE user_id=?", (user_id,))
    if account:
        return TelegramNotifier(token=notifier.token, chat_id=account["chat_id"],
                                session=notifier.session)
    user = db.one("SELECT role,username FROM users WHERE id=?", (user_id,))
    if user and user["role"] == "admin" and user["username"] == "admin":
        return notifier  # Backwards compatibility for the original local admin.
    return TelegramNotifier(token=getattr(notifier, "token", ""), chat_id="")
