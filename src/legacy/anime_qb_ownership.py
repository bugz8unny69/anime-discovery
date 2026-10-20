"""Durable qBittorrent provenance; default to preserving torrents.

An exact matching info hash is evidence of existence, NOT authorship.
Only a marker precommitted to SQLite before Anime Discovery's own
category-tagged add, subsequently found on the exact hash, proves ownership.
Old installs and uncertain/crashed submissions are preserved by default.
"""
import re
import time
import uuid

CATEGORY="anime-discovery"
OWNED="OWNED"
EXTERNAL="EXTERNAL"
UNCERTAIN="UNCERTAIN"
VALID=(OWNED,EXTERNAL,UNCERTAIN)

def normalize(infohash):
    if not isinstance(infohash,str) or not re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})",infohash):
        raise ValueError("Invalid torrent infohash")
    return infohash.lower()

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS qb_torrent_ownership (
        infohash TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK(status IN ('OWNED','EXTERNAL','UNCERTAIN')),
        marker TEXT UNIQUE,
        category TEXT NOT NULL,
        updated_at INTEGER NOT NULL)""")

def ownership(db,infohash):
    infohash=normalize(infohash)
    ensure_schema(db)
    row=db.execute("SELECT status FROM qb_torrent_ownership WHERE infohash=?",(infohash,)).fetchone()
    return row[0] if row else UNCERTAIN

def ownership_for_series(db,series_id):
    """Read-only report; treat missing/old ownership records as uncertain."""
    tables={r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    rows=db.execute("""SELECT DISTINCT lower(r.infohash)
        FROM torrent_recovery_records r
        JOIN episode_dispatch d ON d.notification_id=r.notification_id
        WHERE d.series_id=? AND d.state='DONE'""",(series_id,)).fetchall()
    if not rows:
        return []
    known={}
    if "qb_torrent_ownership" in tables:
        known={h:status for h,status in db.execute(
            "SELECT infohash,status FROM qb_torrent_ownership")}
    return [{"infohash":h,"ownership":known.get(h,UNCERTAIN)} for (h,) in rows]

def reserve_marker(db,infohash):
    """Durably reserve an unpredictable qB tag before the external write."""
    infohash=normalize(infohash)
    ensure_schema(db)
    row=db.execute("SELECT status,marker FROM qb_torrent_ownership WHERE infohash=?",(infohash,)).fetchone()
    if row:
        return row[1] if row[0]==UNCERTAIN else None
    marker="ad-"+uuid.uuid4().hex
    db.execute("INSERT INTO qb_torrent_ownership VALUES (?,?,?,?,?)",
               (infohash,UNCERTAIN,marker,CATEGORY,int(time.time())))
    return marker

def mark_external(db,infohash):
    infohash=normalize(infohash)
    ensure_schema(db)
    existing=ownership(db,infohash)
    if existing==OWNED:
        return  # Preserve previously proven ownership.
    db.execute("""INSERT INTO qb_torrent_ownership(infohash,status,marker,category,updated_at)
        VALUES (?,'EXTERNAL',NULL,?,?)
        ON CONFLICT(infohash) DO UPDATE SET
        status='EXTERNAL',marker=NULL,updated_at=excluded.updated_at
        WHERE status!='OWNED'""",(infohash,CATEGORY,int(time.time())))

def confirm_marker(db,infohash,qb):
    """Authoritative readback of the marker on the exact torrent hash."""
    infohash=normalize(infohash)
    ensure_schema(db)
    row=db.execute("SELECT status,marker FROM qb_torrent_ownership WHERE infohash=?",(infohash,)).fetchone()
    if not row or row[0]==EXTERNAL:
        return False
    if row[0]==OWNED:
        return True
    marker=row[1]
    if not marker:
        return False
    # Use an exact-hash read. This does not depend on qB metadata/save_path
    # being populated while a newly submitted magnet is fetching metadata.
    record=qb.torrent_identity(infohash)
    if record is None:
        return False
    labels=record.get("tags","")
    tags={tag.strip() for tag in labels.split(",")} if isinstance(labels,str) else set()
    if record.get("category")!=CATEGORY or marker not in tags:
        return False
    db.execute("""UPDATE qb_torrent_ownership SET status='OWNED',updated_at=?
                  WHERE infohash=? AND status='UNCERTAIN' AND marker=?""",
               (int(time.time()),infohash,marker))
    return True

def owned_now(db,infohash,qb):
    """Recheck the marker immediately before destructive cleanup.

    An earlier proof is insufficient if the torrent was deleted and later
    replaced, recategorized or retagged by another client.
    """
    infohash=normalize(infohash)
    if ownership(db,infohash)!=OWNED:
        return False
    row=db.execute("SELECT marker FROM qb_torrent_ownership WHERE infohash=?",
                   (infohash,)).fetchone()
    marker=row[0] if row else None
    if not marker:
        return False
    try:
        current=qb.torrent_identity(infohash)
    except (OSError,ValueError,RuntimeError):
        current=None
    if current is not None:
        tags=current.get("tags","")
        labels={part.strip() for part in tags.split(",")} if isinstance(tags,str) else set()
        if current.get("category")==CATEGORY and marker in labels:
            return True
    # Degrade an old ownership decision to uncertain, never promote an
    # externally discovered source. Even a qB outage leaves files untouched.
    db.execute("""UPDATE qb_torrent_ownership SET status='UNCERTAIN',updated_at=?
        WHERE infohash=? AND status='OWNED'""",(int(time.time()),infohash))
    return False
