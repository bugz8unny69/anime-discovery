"""Shared SQLite runtime primitives for the unified Anime Discovery database.

Opt-in foundation only: callers must be migrated explicitly; this module does
not silently rewrite existing controller/inbox databases.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

DEFAULT_DB_PATH = Path("/var/lib/anime-discovery/anime-discovery.db")
DB_ENV_VAR = "ANIME_DISCOVERY_DB_PATH"


def database_path() -> Path:
    """Return the canonical database path (override intended for tests)."""
    raw = os.environ.get(DB_ENV_VAR)
    if raw is not None:
        if not raw.strip():
            raise ValueError(f"{DB_ENV_VAR} must not be empty")
        return Path(raw).expanduser().resolve()
    return DEFAULT_DB_PATH


def connect(path: str | os.PathLike[str] | None = None, *, read_only: bool = False) -> sqlite3.Connection:
    """Open a short-lived SQLite connection with consistent safety settings.

    Does not create the parent directory. Read-only mode must not create the DB.
    The caller owns the returned connection and must close it.
    """
    target = Path(path) if path is not None else database_path()
    if read_only:
        db = sqlite3.connect(target.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    else:
        db = sqlite3.connect(str(target), timeout=10)
    try:
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        if not read_only:
            db.execute("PRAGMA journal_mode=WAL")
        return db
    except BaseException:
        db.close()
        raise


@contextmanager
def transaction(path: str | os.PathLike[str] | None = None) -> Iterator[sqlite3.Connection]:
    """Acquire a write transaction and commit or roll back atomically."""
    db = connect(path)
    try:
        db.execute("BEGIN IMMEDIATE")
        try:
            yield db
        except BaseException:
            db.rollback()
            raise
        else:
            db.commit()
    finally:
        db.close()
