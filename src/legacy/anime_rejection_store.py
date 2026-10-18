"""Show-level rejection state for the unified SQLite database.

A history purge must never remove these blockers. Reset is a separate,
explicit, audited operation. No filesystem or torrent deletion occurs here.
"""
from __future__ import annotations
import sqlite3
import time


def ensure_schema(db: sqlite3.Connection) -> None:
    db.executescript("""
    CREATE TABLE IF NOT EXISTS series_rejection_blocks (
        series_id INTEGER PRIMARY KEY REFERENCES series(id) ON DELETE RESTRICT,
        reason TEXT NOT NULL,
        blocked_at INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS series_admin_audit (
        id INTEGER PRIMARY KEY,
        series_id INTEGER NOT NULL,
        action TEXT NOT NULL,
        occurred_at INTEGER NOT NULL,
        details TEXT NOT NULL
    );
    """)


def is_blocked(db: sqlite3.Connection, series_id: int) -> bool:
    """Fail closed when the blocker table is missing or inaccessible."""
    return db.execute(
        "SELECT 1 FROM series_rejection_blocks WHERE series_id=?", (series_id,)
    ).fetchone() is not None


def reject(db: sqlite3.Connection, series_id: int, reason: str) -> None:
    if not reason.strip():
        raise ValueError("Rejection reason required")
    if db.execute("SELECT 1 FROM series WHERE id=?", (series_id,)).fetchone() is None:
        raise ValueError("Unknown series")
    now = int(time.time())
    db.execute(
        "INSERT INTO series_rejection_blocks(series_id,reason,blocked_at) "
        "VALUES (?,?,?) ON CONFLICT(series_id) DO UPDATE SET reason=excluded.reason",
        (series_id, reason, now),
    )
    db.execute(
        "INSERT INTO series_admin_audit(series_id,action,occurred_at,details) VALUES (?,?,?,?)",
        (series_id, "REJECT", now, reason),
    )


def reset_rejection(db: sqlite3.Connection, series_id: int, *, confirmed: bool = False) -> bool:
    """Explicit blocker removal only; caller must own transaction and authorization."""
    if not confirmed:
        raise PermissionError("Reset requires explicit confirmation")
    if db.execute("SELECT 1 FROM series WHERE id=?", (series_id,)).fetchone() is None:
        raise ValueError("Unknown series")
    cursor = db.execute("DELETE FROM series_rejection_blocks WHERE series_id=?", (series_id,))
    db.execute(
        "INSERT INTO series_admin_audit(series_id,action,occurred_at,details) VALUES (?,?,?,?)",
        (series_id, "RESET_REJECTION", int(time.time()), "explicit confirmed reset"),
    )
    return cursor.rowcount > 0
