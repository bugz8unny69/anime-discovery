"""Cached verified series mapping and qBittorrent scheduling policy.

No qBittorrent active-download limit is set here. The torrent client owns
download concurrency and queue ordering unless the user opts in otherwise.
"""
import sqlite3
import time

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS verified_series_cache (
        source TEXT NOT NULL,
        external_id TEXT NOT NULL,
        anidb_id TEXT NOT NULL,
        tvdb_id TEXT NOT NULL,
        ordering_json TEXT NOT NULL,
        evidence_hash TEXT NOT NULL,
        verified_at INTEGER NOT NULL,
        PRIMARY KEY(source,external_id)
    )""")

def cached_mapping(db, source, external_id):
    row=db.execute("""SELECT anidb_id,tvdb_id,ordering_json,evidence_hash,verified_at
        FROM verified_series_cache WHERE source=? AND external_id=?""",
        (source,external_id)).fetchone()
    if not row:
        return None
    return dict(zip(("anidb_id","tvdb_id","ordering_json","evidence_hash","verified_at"),row))

def store_verified(db, *, source, external_id, anidb_id, tvdb_id, ordering_json, evidence_hash):
    if not all(isinstance(x,str) and x.strip() for x in
               (source,external_id,anidb_id,tvdb_id,ordering_json,evidence_hash)):
        raise ValueError("Verified mapping requires complete evidence")
    if not anidb_id.isdigit() or not tvdb_id.isdigit():
        raise ValueError("Invalid identity IDs")
    existing=cached_mapping(db,source,external_id)
    if existing and (existing["anidb_id"],existing["tvdb_id"])!=(anidb_id,tvdb_id):
        raise ValueError("Identity conflict requires review")
    db.execute("""INSERT INTO verified_series_cache
        (source,external_id,anidb_id,tvdb_id,ordering_json,evidence_hash,verified_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(source,external_id) DO UPDATE SET
        ordering_json=excluded.ordering_json,evidence_hash=excluded.evidence_hash,
        verified_at=excluded.verified_at""",
        (source,external_id,anidb_id,tvdb_id,ordering_json,evidence_hash,int(time.time())))

def torrent_submission_options(*, priority_mode="normal"):
    """Return only optional torrent fields; never override client queue limits."""
    if priority_mode=="normal":
        return {}
    raise ValueError("Unsupported priority policy; no override applied")
