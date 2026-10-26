"""Durable payment receipts, queued atomically with Pro activation."""

import threading
import time
import logging

from .db import now
from .telegram_link import recipient_for
from .onboarding import pro_guide

log = logging.getLogger(__name__)


def enqueue_receipts(conn, order_id):
    for channel in ("email", "telegram"):
        conn.execute(
            "INSERT OR IGNORE INTO billing_notifications(order_id,channel) VALUES(?,?)",
            (order_id, channel),
        )


class BillingNotifications:
    def __init__(self, db, email_sender, notifier):
        self.db, self.email_sender, self.notifier = db, email_sender, notifier
        self.stop = threading.Event()
        self.wake = threading.Event()
        self.thread = None

    def start(self):
        self.thread = threading.Thread(target=self.loop, name="lh25-payment-receipts", daemon=True)
        self.thread.start()

    def close(self):
        self.stop.set()
        self.wake.set()
        if self.thread:
            self.thread.join(timeout=30)

    def loop(self):
        while not self.stop.is_set():
            try:
                processed = self.run_once()
            except Exception:
                log.warning("Payment receipt dispatcher will retry after a database error")
                processed = False
            if not processed:
                self.wake.wait(15)
                self.wake.clear()

    def run_once(self):
        stamp = time.time()
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM billing_notifications WHERE status IN ('pending','processing') "
                "AND next_attempt<=? ORDER BY id LIMIT 1", (stamp,),
            ).fetchone()
            if not row:
                return False
            row = dict(row)
            conn.execute(
                "UPDATE billing_notifications SET status='processing',attempts=attempts+1,next_attempt=? WHERE id=?",
                (stamp + 120, row["id"]),
            )
        delivered = False
        try:
            order = self.db.one(
                "SELECT o.*,s.expires_at,p.email,e.email verified_email,e.verified_at "
                "FROM orders o JOIN subscriptions s ON s.user_id=o.user_id "
                "LEFT JOIN customer_profiles p ON p.user_id=o.user_id "
                "LEFT JOIN email_verifications e ON e.user_id=o.user_id WHERE o.id=?",
                (row["order_id"],),
            )
            if order and order["status"] == "activated":
                message = (f"LH25 · Đã mở gói Pro\nMã đơn: {order['id']}\n"
                           f"Thanh toán: {order['amount_vnd']:,} VND\n"
                           f"Hết hạn (UTC): {order['expires_at']}")
                if row["channel"] == "email":
                    if order["verified_at"] and order["email"] == order["verified_email"]:
                        self.email_sender.send_payment_confirmation(order["email"], message + pro_guide())
                        delivered = True
                else:
                    delivered = recipient_for(self.db, order["user_id"], self.notifier).send_text(message)
        except Exception:
            # Never put SMTP/Telegram URLs, addresses or credentials into diagnostics.
            delivered = False
        attempts = row["attempts"] + 1
        self.db.execute(
            "UPDATE billing_notifications SET status=?,delivered_at=?,next_attempt=?,last_error=? WHERE id=?",
            ("delivered" if delivered else "failed" if attempts >= 5 else "pending",
             now() if delivered else None, stamp + min(3600, 30 * 2 ** attempts),
             "" if delivered else "delivery_failed", row["id"]),
        )
        return True
