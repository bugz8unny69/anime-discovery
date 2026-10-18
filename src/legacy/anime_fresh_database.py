"""Fresh-install SQLite foundation. Never imports legacy data or starts workers."""
import sqlite3
from pathlib import Path
from anime_async_daemon import ensure_schema
from anime_external_actions import ensure_schema as ensure_actions
from anime_series_cache import ensure_schema as ensure_cache

SCHEMA_VERSION = 1

def initialize(path):
    path = Path(path)
    if path.is_symlink() or path.exists():
        raise FileExistsError("Fresh database path already exists: "+str(path))
    if not path.parent.is_dir():
        raise ValueError("Fresh database parent directory must exist")
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
                db.execute("""CREATE TABLE migration_quarantined_series (
                    series_id INTEGER PRIMARY KEY REFERENCES series(id),
                    reason TEXT NOT NULL,
                    quarantined_at INTEGER NOT NULL
                )""")
                db.execute("""CREATE TABLE series_rejection_blocks (
                    series_id INTEGER PRIMARY KEY REFERENCES series(id),
                    reason TEXT NOT NULL DEFAULT 'REJECTED'
                )""")
                db.execute("""CREATE TABLE verified_series_identity (
                    notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
                    anidb_id TEXT NOT NULL,
                    tvdb_id TEXT NOT NULL,
                    mapping_source TEXT NOT NULL,
                    decision TEXT NOT NULL,
                    episode_identity_verified INTEGER NOT NULL DEFAULT 0,
                    eligible_for_acquisition INTEGER NOT NULL DEFAULT 0,
                    evidence_json TEXT NOT NULL,
                    evidence_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )""")
                db.execute("""CREATE TABLE episode_verification_v16 (
                    notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
                    evaluated_at REAL NOT NULL,
                    decision TEXT NOT NULL,
                    verified INTEGER NOT NULL DEFAULT 0 CHECK(verified IN (0,1)),
                    evidence_json TEXT NOT NULL
                )""")
                db.execute("""CREATE TABLE episode_approval_queue (
                    notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
                    decision TEXT NOT NULL DEFAULT 'NEEDS_REVIEW',
                    season INTEGER NOT NULL CHECK(season>=0),
                    episode INTEGER NOT NULL CHECK(episode>0)
                )""")
                db.execute("""CREATE TABLE episode_dispatch (
                    notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
                    series_id INTEGER NOT NULL REFERENCES series(id),
                    season INTEGER NOT NULL CHECK(season>=0),
                    episode INTEGER NOT NULL CHECK(episode>0),
                    state TEXT NOT NULL DEFAULT 'NEEDS_REVIEW',
                    last_error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts>=0),
                    updated_at INTEGER NOT NULL DEFAULT 0
                )""")
                db.execute("""CREATE TABLE torrent_recovery_records (
                    notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
                    infohash TEXT NOT NULL,
                    magnet_uri TEXT NOT NULL,
                    staged_path TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    recorded_at INTEGER NOT NULL
                )""")
                ensure_actions(db)
                ensure_cache(db)
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
