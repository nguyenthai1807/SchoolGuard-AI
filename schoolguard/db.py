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
            conn.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL, role TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), expires REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY, name TEXT NOT NULL, path TEXT NOT NULL, kind TEXT NOT NULL, split TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES sources(id), status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT, finished_at TEXT, config TEXT NOT NULL, progress REAL NOT NULL DEFAULT 0, frames INTEGER NOT NULL DEFAULT 0, total_frames INTEGER NOT NULL DEFAULT 0, people INTEGER NOT NULL DEFAULT 0, events INTEGER NOT NULL DEFAULT 0, fps REAL NOT NULL DEFAULT 0, cancel INTEGER NOT NULL DEFAULT 0, error TEXT, summary TEXT, user_id INTEGER NOT NULL REFERENCES users(id));
                CREATE TABLE IF NOT EXISTS alerts(id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id), created_at TEXT NOT NULL, video_time REAL NOT NULL, zone TEXT NOT NULL, track_id INTEGER NOT NULL, confidence REAL NOT NULL, bbox TEXT NOT NULL, dwell REAL NOT NULL, evidence TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new', note TEXT NOT NULL DEFAULT '', reviewed_by INTEGER REFERENCES users(id));
                CREATE INDEX IF NOT EXISTS alerts_job ON alerts(job_id);
                CREATE INDEX IF NOT EXISTS alerts_status ON alerts(status,created_at);
                CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY, at TEXT NOT NULL, user_id INTEGER, action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
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
            conn.execute("PRAGMA user_version=2")

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
