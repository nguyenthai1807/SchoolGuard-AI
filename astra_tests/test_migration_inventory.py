import sqlite3

from schoolguard.migration_inventory import inventory


def test_inventory_reports_counts_without_rows_paths_or_media_contents(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    db = runtime / "schoolguard.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, email TEXT NOT NULL)")
        connection.execute("INSERT INTO users(email) VALUES(?)", ("private@example.com",))
        connection.execute('CREATE TABLE "private@example.com" (id INTEGER)')
    (runtime / "uploads").mkdir()
    (runtime / "uploads" / "private-video.mp4").write_bytes(b"private video")

    report = inventory(runtime)
    assert report["database"]["tables"] == {"users": 1}
    assert report["database"]["unknown_tables"] == 1
    assert report["database"]["source_splits"] == {}
    assert report["database"]["quick_check_ok"] is True
    assert report["database"]["foreign_key_violations"] == 0
    assert report["media"]["uploads"]["files"] == 1
    assert report["media"]["uploads"]["bytes"] == len(b"private video")
    assert len(report["database"]["schema_sha256"]) == 64
    assert "private@example.com" not in str(report)
    assert "private-video.mp4" not in str(report)
    assert str(runtime) not in str(report)


def test_missing_runtime_is_safe_and_does_not_create_database(tmp_path):
    runtime = tmp_path / "missing"
    report = inventory(runtime)
    assert report["database"] == {
        "present": False, "bytes": 0, "schema_sha256": None, "tables": {},
        "unknown_tables": 0,
        "source_splits": {}, "job_source_splits": {}, "source_files": {},
        "quick_check_ok": None, "foreign_key_violations": None
    }
    assert not runtime.exists()


def test_source_file_audit_only_probes_managed_runtime_and_hides_paths(tmp_path):
    runtime = tmp_path / "runtime"
    runtime.mkdir()
    local_video = runtime / "uploads" / "private-video.mp4"
    local_video.parent.mkdir()
    local_video.write_bytes(b"video")
    db = runtime / "schoolguard.sqlite3"
    with sqlite3.connect(db) as connection:
        connection.execute("CREATE TABLE sources (id TEXT PRIMARY KEY, split TEXT, path TEXT)")
        connection.executemany(
            "INSERT INTO sources VALUES (?,?,?)",
            [
                ("a", "uploaded", str(local_video)),
                ("b", "uploaded", str(runtime / "uploads" / "missing.mp4")),
                ("c", "research", str(tmp_path / "do-not-probe.mp4")),
                ("d", "personal@example.com", "relative-private.mp4"),
            ],
        )
    report = inventory(runtime)
    assert report["database"]["source_files"] == {
        "uploaded": {"local_present": 1, "local_missing": 1, "external_or_relative": 0},
        "research": {"local_present": 0, "local_missing": 0, "external_or_relative": 1},
        "other": {"local_present": 0, "local_missing": 0, "external_or_relative": 1},
    }
    assert "personal@example.com" not in str(report)
    assert "private-video.mp4" not in str(report)
