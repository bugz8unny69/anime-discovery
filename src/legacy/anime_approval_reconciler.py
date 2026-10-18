"""Offline-safe bridge from persisted V16 evidence to the approval queue.

Runs against an already unified database. Does not call torrent APIs or modify
media. Replays are idempotent. Run under the existing worker/service scheduler.
"""
import argparse
import json
import sqlite3
from pathlib import Path

from anime_approval_handoff import handoff
from anime_identity_rejection_gate import IdentityNotReady, SeriesBlocked


def reconcile(db: sqlite3.Connection, limit: int = 100) -> dict:
    if not 1 <= limit <= 1000:
        raise ValueError("Invalid batch limit")
    # Never silently create missing evidence tables: a partial migration fails.
    rows = db.execute("""
        SELECT v.notification_id, s.evidence_json, v.evidence_json
        FROM episode_verification_v16 AS v
        JOIN confidence_shadow_v15 AS s ON s.notification_id=v.notification_id
        JOIN notifications AS n ON n.id=v.notification_id
        LEFT JOIN episode_approval_queue AS q ON q.notification_id=v.notification_id
        WHERE n.status='UNTRUSTED' AND q.notification_id IS NULL
        ORDER BY v.notification_id LIMIT ?
    """, (limit,)).fetchall()
    outcome = {"auto_approved":0, "needs_review":0, "blocked":0, "deferred":0, "errors":0}
    for nid, shadow_json, verification_json in rows:
        try:
            shadow = json.loads(shadow_json)
            verification = json.loads(verification_json)
            result = handoff(db, nid, shadow, verification)
            key = {"AUTO_APPROVED":"auto_approved", "NEEDS_REVIEW":"needs_review"}.get(result["decision"])
            if key is None:
                raise ValueError("Unexpected decision")
            outcome[key] += 1
        except SeriesBlocked:
            outcome["blocked"] += 1
        except IdentityNotReady:
            outcome["deferred"] += 1
        except (ValueError, sqlite3.Error, TypeError, KeyError):
            outcome["errors"] += 1
    return outcome


def main(argv=None):
    p = argparse.ArgumentParser(description="Reconcile existing verified evidence; no torrent or media actions")
    p.add_argument("--db", type=Path, required=True)
    p.add_argument("--limit", type=int, default=100)
    args = p.parse_args(argv)
    if not args.db.is_file():
        p.error("Existing unified database required")
    with sqlite3.connect(f"file:{args.db.resolve()}?mode=rw", uri=True, isolation_level=None, timeout=10) as db:
        db.execute("PRAGMA foreign_keys=ON")
        print(json.dumps(reconcile(db, args.limit), sort_keys=True))


if __name__ == "__main__":
    main()
