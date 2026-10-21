#!/usr/bin/env python3
"""One-time legacy notification -> identity job migration.

Dry-run by default. Run with --apply while Anime Discovery is STOPPED.
Do not put this script in the worker's startup path.
"""
import argparse
import json
import sqlite3
from pathlib import Path

PENDING = ("UNTRUSTED", "RECEIVED", "IDENTIFYING")


def migrate(db, *, apply=False):
    required = {"notifications", "episode_dispatch", "daemon_jobs"}
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    if not required <= tables:
        raise RuntimeError("Missing required tables: " + ", ".join(sorted(required-tables)))
    rows = db.execute("""SELECT n.id,n.status FROM notifications n
        WHERE n.status IN ('UNTRUSTED','RECEIVED','IDENTIFYING')
          AND NOT EXISTS(SELECT 1 FROM episode_dispatch d
                         WHERE d.notification_id=n.id)
        ORDER BY n.id""").fetchall()
    missing = []
    existing = 0
    for nid, status in rows:
        found = db.execute("""SELECT payload_json FROM daemon_jobs
            WHERE kind='identity_resolution' AND subject_key=?""",
            ("notification:" + str(nid),)).fetchone()
        payload = json.dumps({"notification_id": nid}, sort_keys=True)
        if found:
            if found[0] != payload:
                raise RuntimeError("Conflicting identity job payload for notification " + str(nid))
            existing += 1
        else:
            missing.append((nid, status, payload))
    if not apply:
        return {"mode": "dry-run", "pending_notifications": len(rows),
                "already_queued": existing, "jobs_to_create": len(missing)}
    # All changes in one transaction: jobs and notification status agree.
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS anime_job_lineage (
            job_id INTEGER PRIMARY KEY REFERENCES daemon_jobs(id),
            triggered_by_job_id INTEGER REFERENCES daemon_jobs(id),
            notification_id INTEGER,
            created_at REAL NOT NULL,
            CHECK(triggered_by_job_id IS NULL OR job_id != triggered_by_job_id)
        )""")
        for nid, status, payload in missing:
            jid = db.execute("""INSERT INTO daemon_jobs(kind,subject_key,payload_json,state)
                VALUES('identity_resolution',?,?,'READY')""",
                ("notification:" + str(nid), payload)).lastrowid
            db.execute("""INSERT INTO anime_job_lineage
                (job_id,triggered_by_job_id,notification_id,created_at)
                VALUES (?,NULL,?,strftime('%s','now'))""", (jid,nid))
        for nid, status in rows:
            if status in ("UNTRUSTED", "RECEIVED"):
                db.execute("""UPDATE notifications SET status='IDENTIFYING'
                    WHERE id=? AND status=?""", (nid,status))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"mode": "applied", "pending_notifications": len(rows),
            "already_queued": existing, "jobs_created": len(missing)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True,
                        help="Existing Anime Discovery SQLite database")
    parser.add_argument("--apply", action="store_true",
                        help="Apply migration (requires Anime Discovery stopped)")
    args=parser.parse_args()
    if not args.db.is_file() or args.db.is_symlink():
        parser.error("--db must be an existing regular database file")
    if not args.apply:
        uri = "file:" + str(args.db.resolve()) + "?mode=ro"
        db=sqlite3.connect(uri,uri=True,timeout=10,isolation_level=None)
    else:
        db=sqlite3.connect(args.db,timeout=10,isolation_level=None)
    with db:
        db.execute("PRAGMA busy_timeout=10000")
        print(json.dumps(migrate(db,apply=args.apply),sort_keys=True))


if __name__=="__main__":
    main()
