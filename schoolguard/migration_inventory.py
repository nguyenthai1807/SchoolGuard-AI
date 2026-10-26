"""Read-only, identifier-free inventory for a future durable-data migration.

This intentionally does not export SQLite rows, media paths, account names,
addresses, or file contents. It can run while the local service is online.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from urllib.parse import quote


MEDIA_DIRECTORIES = ("uploads", "jobs", "faces", "live")
KNOWN_SOURCE_SPLITS = {"uploaded", "research", "training", "testing", "live"}
KNOWN_TABLES = {
    "alerts", "audit", "billing_notifications", "customer_profiles", "daily_camera_usage",
    "demo_videos", "email_verifications", "faces", "google_identities", "jobs",
    "notification_reads", "orders", "sessions", "source_ownership", "sources",
    "subscriptions", "telegram_accounts", "telegram_pending", "telegram_poll", "users",
}


def _quote_identifier(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'


def _database_inventory(path: Path) -> dict:
    if not path.is_file():
        return {"present": False, "bytes": 0, "schema_sha256": None, "tables": {},
                "unknown_tables": 0,
                "source_splits": {}, "job_source_splits": {}, "source_files": {},
                "quick_check_ok": None, "foreign_key_violations": None}
    uri = "file:" + quote(str(path.resolve()).replace("\\", "/"), safe="/:  ") + "?mode=ro"
    # The URI is read-only, and query_only prevents accidental writes even if
    # a caller changes the queries later.
    with sqlite3.connect(uri, uri=True, timeout=5) as connection:
        connection.execute("PRAGMA query_only = ON")
        rows = connection.execute(
            "SELECT name,sql FROM sqlite_master "
            "WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        counts = {
            name: connection.execute(f"SELECT COUNT(*) FROM {_quote_identifier(name)}").fetchone()[0]
            for name, _ in rows if name in KNOWN_TABLES
        }
        unknown_tables = sum(name not in KNOWN_TABLES for name, _ in rows)
        schema = "\n".join(sql or "" for _, sql in rows)
        quick_check_ok = connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        foreign_key_violations = sum(1 for _ in connection.execute("PRAGMA foreign_key_check"))
        # Source split is an application-controlled category. Unknown values
        # are grouped so this report cannot echo a user-controlled string.
        source_splits = {}
        job_source_splits = {}
        source_files = {}
        if "sources" in counts:
            for split, count in connection.execute(
                "SELECT split,COUNT(*) FROM sources GROUP BY split"
            ):
                label = split if split in KNOWN_SOURCE_SPLITS else "other"
                source_splits[label] = source_splits.get(label, 0) + count
            runtime = path.parent.resolve()
            for split, raw_path in connection.execute("SELECT split,path FROM sources"):
                label = split if split in KNOWN_SOURCE_SPLITS else "other"
                tally = source_files.setdefault(label, {"local_present": 0, "local_missing": 0,
                                                        "external_or_relative": 0})
                candidate = Path(raw_path)
                # Never probe external paths (including network shares). This
                # audit only checks files stored under the managed runtime.
                if not candidate.is_absolute() or not candidate.is_relative_to(runtime):
                    tally["external_or_relative"] += 1
                    continue
                resolved = candidate.resolve(strict=False)
                if not resolved.is_relative_to(runtime):
                    tally["external_or_relative"] += 1
                elif resolved.is_file():
                    tally["local_present"] += 1
                else:
                    tally["local_missing"] += 1
        if "jobs" in counts and "sources" in counts:
            for split, count in connection.execute(
                "SELECT s.split,COUNT(*) FROM jobs j "
                "JOIN sources s ON s.id=j.source_id GROUP BY s.split"
            ):
                label = split if split in KNOWN_SOURCE_SPLITS else "other"
                job_source_splits[label] = job_source_splits.get(label, 0) + count
    return {
        "present": True,
        "bytes": path.stat().st_size,
        "schema_sha256": hashlib.sha256(schema.encode("utf-8")).hexdigest(),
        "tables": counts,
        "unknown_tables": unknown_tables,
        "source_splits": source_splits,
        "job_source_splits": job_source_splits,
        "source_files": source_files,
        "quick_check_ok": quick_check_ok,
        "foreign_key_violations": foreign_key_violations,
    }


def _directory_inventory(path: Path) -> dict:
    files = 0
    total_bytes = 0
    skipped_links = 0
    if not path.is_dir():
        return {"files": 0, "bytes": 0, "skipped_links": 0}
    for item in path.rglob("*"):
        if item.is_symlink():
            skipped_links += 1
        elif item.is_file():
            files += 1
            total_bytes += item.stat().st_size
    return {"files": files, "bytes": total_bytes, "skipped_links": skipped_links}


def inventory(runtime: Path) -> dict:
    """Return counts only; never include paths or record values in the report."""
    return {
        "format": 1,
        "database": _database_inventory(runtime / "schoolguard.sqlite3"),
        "media": {name: _directory_inventory(runtime / name) for name in MEDIA_DIRECTORIES},
        "note": "Counts only; not a backup or migration. Check permissions, retention and restore separately.",
    }
