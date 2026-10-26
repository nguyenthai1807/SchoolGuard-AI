import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone


def now():
    return datetime.now(timezone.utc).isoformat()


class Database:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            had_subscriptions = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='subscriptions'"
            ).fetchone() is not None
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS customer_profiles(user_id INTEGER PRIMARY KEY REFERENCES users(id), display_name TEXT NOT NULL, email TEXT NOT NULL, phone TEXT NOT NULL DEFAULT '', updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL, split TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS demo_videos(source_id TEXT NOT NULL REFERENCES sources(id), capability TEXT NOT NULL, evidence_job_id TEXT NOT NULL REFERENCES jobs(id), rights_note TEXT NOT NULL, review_note TEXT NOT NULL, reviewed_by INTEGER NOT NULL REFERENCES users(id), reviewed_at TEXT NOT NULL, PRIMARY KEY(source_id,capability));
                CREATE INDEX IF NOT EXISTS demo_videos_capability ON demo_videos(capability,reviewed_at);
                CREATE TABLE IF NOT EXISTS source_ownership(source_id TEXT PRIMARY KEY REFERENCES sources(id), user_id INTEGER NOT NULL REFERENCES users(id));
                CREATE INDEX IF NOT EXISTS source_ownership_user ON source_ownership(user_id);
                CREATE TABLE IF NOT EXISTS telegram_accounts(user_id INTEGER PRIMARY KEY REFERENCES users(id), chat_id TEXT NOT NULL, verified_at TEXT NOT NULL, telegram_username TEXT NOT NULL DEFAULT '');
                CREATE UNIQUE INDEX IF NOT EXISTS telegram_accounts_chat ON telegram_accounts(chat_id);
                CREATE TABLE IF NOT EXISTS telegram_pending(user_id INTEGER PRIMARY KEY REFERENCES users(id), code_hash TEXT UNIQUE NOT NULL, expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS telegram_poll(id INTEGER PRIMARY KEY CHECK(id=1), next_offset INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO telegram_poll(id,next_offset) VALUES(1,0);
                CREATE TABLE IF NOT EXISTS subscriptions(user_id INTEGER PRIMARY KEY REFERENCES users(id), plan TEXT NOT NULL, expires_at TEXT, source TEXT NOT NULL, updated_at TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), plan TEXT NOT NULL, amount_vnd INTEGER NOT NULL, status TEXT NOT NULL, created_at TEXT NOT NULL, resolved_at TEXT, payment_reference TEXT NOT NULL DEFAULT '', resolved_by INTEGER REFERENCES users(id));
                CREATE INDEX IF NOT EXISTS orders_user ON orders(user_id,created_at);
                CREATE TABLE IF NOT EXISTS billing_notifications(id INTEGER PRIMARY KEY, order_id TEXT NOT NULL REFERENCES orders(id), channel TEXT NOT NULL CHECK(channel IN ('email','telegram')), status TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0, delivered_at TEXT, last_error TEXT NOT NULL DEFAULT '', UNIQUE(order_id,channel));
                CREATE UNIQUE INDEX IF NOT EXISTS orders_payment_reference ON orders(payment_reference) WHERE payment_reference!='';
                CREATE TABLE IF NOT EXISTS email_verifications(user_id INTEGER PRIMARY KEY REFERENCES users(id), email TEXT NOT NULL, token_hash TEXT, expires_at REAL, sent_at REAL, verified_at TEXT);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, config TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, frames INTEGER NOT NULL DEFAULT 0, total_frames INTEGER NOT NULL DEFAULT 0, people INTEGER NOT NULL DEFAULT 0, events INTEGER NOT NULL DEFAULT 0, fps REAL NOT NULL DEFAULT 0, cancel INTEGER NOT NULL DEFAULT 0, error TEXT, summary TEXT, user_id INTEGER NOT NULL REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS notification_reads(user_id INTEGER NOT NULL REFERENCES users(id), item_id TEXT NOT NULL, read_at TEXT NOT NULL, PRIMARY KEY(user_id,item_id));
                CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), created_at TEXT NOT NULL, video_time REAL NOT NULL, zone TEXT NOT NULL, track_id INTEGER NOT NULL, confidence REAL NOT NULL, bbox TEXT NOT NULL, dwell REAL NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', note TEXT NOT NULL DEFAULT '', reviewed_by INTEGER REFERENCES users(id));
                CREATE INDEX IF NOT EXISTS alerts_job ON alerts(job_id);
                CREATE INDEX IF NOT EXISTS alerts_status ON alerts(status,created_at);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER, action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS faces(id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL, job_id TEXT NOT NULL REFERENCES jobs(id), day TEXT NOT NULL, ordinal INTEGER NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, video_time REAL NOT NULL, seen_count INTEGER NOT NULL, confidence REAL NOT NULL, embedding BLOB NOT NULL, image TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS faces_scope ON faces(scope,ordinal);
                CREATE INDEX IF NOT EXISTS faces_day ON faces(kind,day);
                PRAGMA user_version=1;
            """)
            columns = {row[1] for row in conn.execute("PRAGMA table_info(alerts)")}
            for name, definition in {
                "event_type": "TEXT NOT NULL DEFAULT 'restricted_zone'",
                "severity": "TEXT NOT NULL DEFAULT 'warning'",
                "details": "TEXT NOT NULL DEFAULT '{}'",
                "telegram_status": "TEXT NOT NULL DEFAULT 'pending'",
            }.items():
                if name not in columns:
                    conn.execute(f"ALTER TABLE alerts ADD COLUMN {name} {definition}")
            telegram_columns = {row[1] for row in conn.execute("PRAGMA table_info(telegram_accounts)")}
            if "telegram_username" not in telegram_columns:
                conn.execute("ALTER TABLE telegram_accounts ADD COLUMN telegram_username TEXT NOT NULL DEFAULT ''")
            if "quota_charged" not in {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}:
                conn.execute("ALTER TABLE jobs ADD COLUMN quota_charged INTEGER NOT NULL DEFAULT 0")
            if "academic_only" not in {row[1] for row in conn.execute("PRAGMA table_info(demo_videos)")}:
                conn.execute("ALTER TABLE demo_videos ADD COLUMN academic_only INTEGER NOT NULL DEFAULT 0")
            order_columns = {row[1] for row in conn.execute("PRAGMA table_info(orders)")}
            for name, definition in {
                "payment_order_code": "INTEGER",
                "payment_link_id": "TEXT",
                "checkout_url": "TEXT",
                "paid_at": "TEXT",
            }.items():
                if name not in order_columns:
                    conn.execute(f"ALTER TABLE orders ADD COLUMN {name} {definition}")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS orders_payment_code ON orders(payment_order_code) WHERE payment_order_code IS NOT NULL")
            conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS orders_payment_link ON orders(payment_link_id) WHERE payment_link_id IS NOT NULL")
            if not had_subscriptions:
                # Preserve existing pilot operators. New public registrations get Free explicitly.
                conn.execute(
                    "INSERT OR IGNORE INTO subscriptions(user_id,plan,expires_at,source,updated_at) "
                    "SELECT id,'pro_local',NULL,'legacy_pilot',? FROM users WHERE role='operator'",
                    (now(),),
                )
            # Old webcam galleries used one global day scope. Keep their images and
            # numbering while separating future recognition by account.
            conn.execute(
                "UPDATE faces SET scope='live:' || (SELECT user_id FROM jobs WHERE id=faces.job_id) "
                "|| ':' || day WHERE kind='live' AND scope='live:' || day"
            )
            conn.execute("PRAGMA user_version=5")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=20)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all(self, sql, args=()):
        with self.connect() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def one(self, sql, args=()):
        values = self.all(sql, args)
        return values[0] if values else None

    def execute(self, sql, args=()):
        with self.connect() as conn:
            conn.execute(sql, args)

    def audit(self, user, action, target, detail=""):
        self.execute(
            "INSERT INTO audit(at,user_id,action,target,detail) VALUES(?,?,?,?,?)",
            (now(), user, action, target, detail),
        )


def public_job(row):
    row = dict(row)
    row["config"] = json.loads(row["config"])
    row["summary"] = json.loads(row["summary"]) if row["summary"] else None
    return row
