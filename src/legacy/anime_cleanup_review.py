"""Read-only, fail-closed resource inventory for canceled acquisition jobs.

A matching infohash is not proof of ownership. This module NEVER calls qB,
unlinks files, or performs external side effects.
"""
import re

HASH = re.compile(r"(?:[a-fA-F0-9]{40}|[a-fA-F0-9]{64})")


def inventory(db, kind, subject_key):
    """Return only durable candidate hashes, never claim cleanup is safe."""
    tables = {row[0] for row in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    candidates = set()
    if kind in ("claimed_acquisition", "verified_batch_acquisition"):
        if "torrent_recovery_records" in tables:
            for (value,) in db.execute(
                "SELECT infohash FROM torrent_recovery_records WHERE notification_id=?",
                (subject_key,)):
                if isinstance(value, str) and HASH.fullmatch(value):
                    candidates.add(value.lower())
        if "anime_batch_authorizations" in tables:
            for (value,) in db.execute(
                "SELECT infohash FROM anime_batch_authorizations WHERE notification_id=?",
                (subject_key,)):
                if isinstance(value, str) and HASH.fullmatch(value):
                    candidates.add(value.lower())
    known = {}
    if "qb_torrent_ownership" in tables:
        known = {h.lower(): status for h, status in db.execute(
            "SELECT infohash,status FROM qb_torrent_ownership")
            if isinstance(h, str)}
    hashes = sorted(candidates)
    return {
        "candidate_hashes": hashes,
        "ownership": {h: known.get(h, "UNCERTAIN") for h in hashes},
        "cleanup_status": "REVIEW_REQUIRED" if hashes else "NOT_VERIFIED",
        "may_delete": False,
        "explanation": ("Resource ownership, sharing and current qB state "
                        "must be revalidated before any deletion."),
    }
