"""Fresh-install SQLite foundation. Never imports legacy data or starts workers."""
import sqlite3
from pathlib import Path
from anime_async_daemon import ensure_schema

SCHEMA_VERSION = 1

def initialize(path):
    path = Path(path)
    if path.is_symlink() or path.exists() or not path.parent.is_dir():
        raise ValueError("Fresh database path must not exist; parent must exist")
    created = False
    try:
        with sqlite3.connect(path, isolation_level=None, timeout=10) as db:
            created = True
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""CREATE TABLE schema_version (
                    version INTEGER NOT NULL CHECK(version=1),
                    installed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                db.execute("INSERT INTO schema_version(version) VALUES (?)", (SCHEMA_VERSION,))
                db.execute("""CREATE TABLE series (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'DISCOVERED',
                    initial_search_complete INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(source,external_id)
                )""")
                db.execute("""CREATE TABLE episodes (
                    series_id INTEGER NOT NULL REFERENCES series(id),
                    season INTEGER NOT NULL CHECK(season>=0),
                    episode INTEGER NOT NULL CHECK(episode>0),
                    status TEXT NOT NULL DEFAULT 'RESERVED',
                    PRIMARY KEY(series_id,season,episode)
                )""")
                db.execute("""CREATE TABLE notifications (
                    id INTEGER PRIMARY KEY,
                    source TEXT NOT NULL,
                    release_name TEXT NOT NULL,
                    source_guid TEXT NOT NULL,
                    info_hash TEXT NOT NULL,
                    received_at INTEGER NOT NULL,
                    status TEXT NOT NULL DEFAULT 'UNTRUSTED',
                    UNIQUE(source,source_guid)
                )""")
                ensure_schema(db)
                if db.execute("PRAGMA foreign_key_check").fetchall():
                    raise ValueError("Foreign-key failure")
                db.commit()
            except BaseException:
                db.rollback()
                raise
            if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise ValueError("Integrity failure")
        return {"schema_version": SCHEMA_VERSION, "fresh": True,
                "acquisition_enabled": False, "workers_started": False}
    except BaseException:
        if created:
            for suffix in ("-wal", "-shm", ""):
                Path(str(path)+suffix).unlink(missing_ok=True)
        raise
