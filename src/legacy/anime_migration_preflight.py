"""Offline readiness checks for a migrated unified database.

Read-only preflight; it never creates schema or authorizes acquisition.
"""
import sqlite3
from pathlib import Path

REQUIRED_TABLES=(
    "series","episodes","notifications","migration_quarantined_series",
    "series_rejection_blocks","verified_series_identity",
    "confidence_shadow_v15","episode_verification_v16",
    "episode_approval_queue","episode_dispatch","daemon_jobs",
    "torrent_recovery_records"
)

def preflight(path):
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as db:
        integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity!="ok":
            raise ValueError("SQLite integrity check failed")
        fk=db.execute("PRAGMA foreign_key_check").fetchall()
        if fk:
            raise ValueError("Foreign key violations detected")
        present={row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing=sorted(set(REQUIRED_TABLES)-present)
        bootstrap=(db.execute("SELECT status FROM schema_bootstrap WHERE id=1").fetchone()
                   if "schema_bootstrap" in present else None)
        return {"ready":not missing and bootstrap is None,
                "missing_tables":missing,
                "bootstrap_status":bootstrap[0] if bootstrap else None,
                "integrity":"ok","foreign_key_violations":0}
