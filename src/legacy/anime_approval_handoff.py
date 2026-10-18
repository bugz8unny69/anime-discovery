"""Atomic auto-approval handoff into a unified SQLite database.

No network, torrent, or filesystem operations. An approved row is a durable
controller work item, not proof that media has been acquired.
"""
from __future__ import annotations
import json
import sqlite3
import time

from anime_auto_approval import decide_episode
from anime_identity_rejection_gate import IdentityNotReady, SeriesBlocked, resolve_notification


def ensure_schema(db: sqlite3.Connection) -> None:
    db.execute("""CREATE TABLE IF NOT EXISTS episode_approval_queue (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        series_id INTEGER NOT NULL REFERENCES series(id),
        season INTEGER CHECK(season > 0),
        episode INTEGER CHECK(episode > 0),
        decision TEXT NOT NULL CHECK(decision IN ('AUTO_APPROVED','NEEDS_REVIEW','BLOCKED')),
        reason TEXT NOT NULL,
        evidence_json TEXT NOT NULL,
        updated_at INTEGER NOT NULL
    )""")


def handoff(db: sqlite3.Connection, notification_id: int, shadow: dict, verification: dict) -> dict:
    """Resolve and record decision within an IMMEDIATE transaction.

    Caller supplies an open connection with foreign_keys=ON. Failures roll back.
    A fresh rejection check runs while the write lock is held, preventing a
    concurrent reject from racing the approval decision.
    """
    if db.in_transaction:
        raise ValueError("handoff requires a connection outside a transaction")
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        try:
            series_id = resolve_notification(db, notification_id)
        except SeriesBlocked:
            raise
        except IdentityNotReady:
            raise
        result = decide_episode(shadow, verification)
        mapping = result.get("mapping") or verification.get("proposed_mapping") or {}
        if result["decision"] == "AUTO_APPROVED":
            verified_tvdb = db.execute("SELECT tvdb_id FROM verified_series_identity WHERE notification_id=?", (notification_id,)).fetchone()[0]
            if str(int(mapping["tvdb_id"])) != str(int(verified_tvdb)):
                raise ValueError("Episode mapping conflicts with verified series identity")
        season = mapping.get("tvdb_season")
        episode = mapping.get("tvdb_episode")
        if type(season) is not int or season < 1 or type(episode) is not int or episode < 1:
            season = episode = None
            if result["decision"] == "AUTO_APPROVED":
                raise ValueError("Approved episode mapping missing")
        existing = db.execute("SELECT series_id,season,episode,decision FROM episode_approval_queue WHERE notification_id=?", (notification_id,)).fetchone()
        if existing:
            if tuple(existing[:3]) != (series_id, season, episode):
                raise ValueError("Conflicting existing notification mapping")
            if existing[3] == "AUTO_APPROVED" and result["decision"] != "AUTO_APPROVED":
                raise ValueError("Previously approved notification needs explicit reconciliation")
        evidence = json.dumps({"shadow":shadow,"verification":verification},sort_keys=True,ensure_ascii=False)
        db.execute("""INSERT INTO episode_approval_queue
            (notification_id,series_id,season,episode,decision,reason,evidence_json,updated_at)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(notification_id) DO UPDATE SET
              decision=excluded.decision,reason=excluded.reason,
              evidence_json=excluded.evidence_json,updated_at=excluded.updated_at""",
            (notification_id,series_id,season,episode,result["decision"],result["reason"],evidence,int(time.time())))
        db.commit()
        return {"notification_id":notification_id,"series_id":series_id,"season":season,"episode":episode,**result}
    except BaseException:
        db.rollback()
        raise
