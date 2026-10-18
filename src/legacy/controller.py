
#!/usr/bin/env python3
import argparse
import os
import sqlite3
from pathlib import Path

DB = Path("/var/lib/anime-discovery/controller.db")
LIMIT = 6

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    id INTEGER PRIMARY KEY,
    source TEXT NOT NULL,
    external_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'DISCOVERED'
        CHECK(status IN (
            'DISCOVERED', 'ACQUIRING', 'PENDING_REVIEW',
            'APPROVED', 'REJECTED', 'NEEDS_REVIEW'
        )),
    UNIQUE(source, external_id)
);

CREATE TABLE IF NOT EXISTS episodes (
    series_id INTEGER NOT NULL REFERENCES series(id),
    season INTEGER NOT NULL,
    episode INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'RESERVED'
        CHECK(status IN ('RESERVED', 'DOWNLOADED', 'FAILED')),
    PRIMARY KEY(series_id, season, episode)
);
"""

def connect():
    DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(DB, timeout=10, isolation_level=None)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=10000")
    db.executescript(SCHEMA)
    return db

def discover(db, args):
    if not args.external_id.strip() or not args.title.strip():
        raise ValueError("A stable ID and title are required")
    db.execute(
        """INSERT OR IGNORE INTO series
           (source, external_id, title) VALUES (?, ?, ?)""",
        (args.source, args.external_id, args.title)
    )
    row = db.execute(
        """SELECT id, status FROM series
           WHERE source=? AND external_id=?""",
        (args.source, args.external_id)
    ).fetchone()
    print(f"Series ID: {row[0]}, status: {row[1]}")

def reserve(db, args):
    if args.season < 1 or args.episode < 1:
        raise ValueError("Only positive regular season/episode numbers")
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            "SELECT status FROM series WHERE id=?",
            (args.id,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown series")
        if row[0] not in ("DISCOVERED", "ACQUIRING"):
            raise ValueError(f"Acquisition blocked: {row[0]}")

        existing = db.execute(
            """SELECT status FROM episodes
               WHERE series_id=? AND season=? AND episode=?""",
            (args.id, args.season, args.episode)
        ).fetchone()
        if existing:
            raise ValueError(f"Episode already tracked: {existing[0]}")

        count = db.execute(
            """SELECT COUNT(*) FROM episodes
               WHERE series_id=? AND status IN
               ('RESERVED', 'DOWNLOADED')""",
            (args.id,)
        ).fetchone()[0]
        if count >= LIMIT:
            raise ValueError("Six-episode limit reached")

        db.execute(
            """INSERT INTO episodes
               (series_id, season, episode)
               VALUES (?, ?, ?)""",
            (args.id, args.season, args.episode)
        )
        db.execute(
            "UPDATE series SET status='ACQUIRING' WHERE id=?",
            (args.id,)
        )
        db.execute("COMMIT")
        print("DRY RUN: episode reserved; no torrent submitted")
    except Exception:
        db.execute("ROLLBACK")
        raise

def update_status(db, args):
    db.execute("BEGIN IMMEDIATE")
    try:
        row = db.execute(
            "SELECT status FROM series WHERE id=?", (args.id,)
        ).fetchone()
        if not row:
            raise ValueError("Unknown series")
        current = row[0]
        allowed = {
            "DISCOVERED": {"PENDING_REVIEW", "NEEDS_REVIEW"},
            "ACQUIRING": {"PENDING_REVIEW", "NEEDS_REVIEW"},
            "PENDING_REVIEW": {"APPROVED", "REJECTED"},
            "NEEDS_REVIEW": {"PENDING_REVIEW"},
        }
        if args.status not in allowed.get(current, set()):
            raise ValueError(f"Invalid transition: {current} -> {args.status}")
        db.execute(
            "UPDATE series SET status=? WHERE id=?",
            (args.status, args.id)
        )
        db.execute("COMMIT")
        print(f"Series {args.id}: {current} -> {args.status}")
    except Exception:
        db.execute("ROLLBACK")
        raise

def list_series(db, args):
    rows = db.execute(
        """SELECT s.id, s.title, s.status,
                  COUNT(e.episode)
           FROM series s
           LEFT JOIN episodes e ON e.series_id=s.id
               AND e.status IN ('RESERVED', 'DOWNLOADED')
           GROUP BY s.id ORDER BY s.id"""
    )
    for sid, title, status, count in rows:
        print(f"{sid:>3} | {count}/{LIMIT} | {status:<15} | {title}")

def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover")
    d.add_argument("--source", required=True)
    d.add_argument("--external-id", required=True)
    d.add_argument("--title", required=True)

    r = sub.add_parser("reserve")
    r.add_argument("--id", type=int, required=True)
    r.add_argument("--season", type=int, required=True)
    r.add_argument("--episode", type=int, required=True)

    s = sub.add_parser("status")
    s.add_argument("--id", type=int, required=True)
    s.add_argument("--status", required=True,
                   choices=["PENDING_REVIEW", "APPROVED",
                            "REJECTED", "NEEDS_REVIEW"])

    sub.add_parser("list")
    args = p.parse_args()

    with connect() as db:
        {
            "discover": discover,
            "reserve": reserve,
            "status": update_status,
            "list": list_series,
        }[args.command](db, args)

if __name__ == "__main__":
    try:
        main()
    except (ValueError, sqlite3.Error) as exc:
        raise SystemExit(f"ERROR: {exc}")

