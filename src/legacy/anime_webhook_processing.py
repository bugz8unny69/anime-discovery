"""Atomic, idempotent Autobrr intake and explicit episode approval.

Webhook metadata can be approved automatically only when it includes both
external series identities and the exact season/episode. Missing identity
stays in the inbox rather than guessing from the release title.
"""
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

from anime_acquisition_gate import approved_dispatch
from anime_async_daemon import ensure_schema

HASH = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _positive(value, label):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(label + " must be a positive integer") from None
    if result <= 0:
        raise ValueError(label + " must be a positive integer")
    return result


def _magnet(value, infohash):
    magnet = str(value or "magnet:?xt=urn:btih:" + infohash)
    parts = urlsplit(magnet)
    identifiers = parse_qs(parts.query).get("xt", [])
    if parts.scheme != "magnet" or len(identifiers) != 1 or identifiers[0].lower() != "urn:btih:" + infohash:
        raise ValueError("Magnet hash does not match notification")
    return magnet


def _approval_values(values):
    tvdb = str(_positive(values.get("tvdb_id"), "tvdb_id"))
    anidb = str(_positive(values.get("anidb_id"), "anidb_id"))
    season = _positive(values.get("season"), "season")
    episode = _positive(values.get("episode"), "episode")
    return tvdb, anidb, season, episode


def approve(db, notification_id, values, *, source="manual"):
    """Create exactly one approved dispatch and acquisition job in one transaction."""
    nid = _positive(notification_id, "notification_id")
    tvdb, anidb, season, episode = _approval_values(values)
    if db.in_transaction:
        raise ValueError("Approval needs autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        notification = db.execute(
            "SELECT release_name,info_hash FROM notifications WHERE id=?", (nid,)).fetchone()
        if notification is None:
            raise ValueError("Notification not found")
        title, infohash = notification
        infohash = infohash.lower()
        magnet = _magnet(values.get("magnet_uri") or values.get("magnet"), infohash)
        existing = db.execute(
            "SELECT id,status FROM series WHERE source='tvdb' AND external_id=?", (tvdb,)).fetchone()
        if existing:
            sid, status = existing
            if status == "REJECTED" or db.execute(
                "SELECT 1 FROM series_rejection_blocks WHERE series_id=?", (sid,)).fetchone():
                raise ValueError("Series rejected; reset before a new acquisition")
            if db.execute("SELECT 1 FROM series_quarantine WHERE series_id=?", (sid,)).fetchone():
                raise ValueError("Series quarantined")
        prior = db.execute("""SELECT d.series_id,d.season,d.episode,v.tvdb_id,v.anidb_id
             FROM episode_dispatch d JOIN verified_series_identity v
             ON v.notification_id=d.notification_id
             WHERE d.notification_id=?""", (nid,)).fetchone()
        if prior:
            if (str(prior[3]),str(prior[4]),prior[1],prior[2]) != (tvdb,anidb,season,episode):
                raise ValueError("Existing approval conflicts with supplied episode identity")
            job = db.execute("""SELECT payload_json FROM daemon_jobs
                WHERE kind='claimed_acquisition' AND subject_key=?""", (str(nid),)).fetchone()
            if job:
                old = json.loads(job[0])
                if old["magnet_uri"] != magnet:
                    raise ValueError("Existing job uses a different magnet")
                db.commit()
                return {"notification_id": nid, "queued": False, "duplicate": True, "series_id": prior[0]}
            # Repair approval persisted by earlier versions before job enqueue.
            approved_dispatch(db, nid)
            sid = prior[0]
        else:
            if not existing:
                sid = db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb',?,?)",
                                 (tvdb,title)).lastrowid
            else:
                sid = existing[0]
            evidence = json.dumps({"source": source, "tvdb_id": tvdb,
                "anidb_id": anidb, "season": season, "episode": episode}, sort_keys=True)
            db.execute("""INSERT INTO verified_series_identity
                (notification_id,anidb_id,tvdb_id,mapping_source,decision,
                 episode_identity_verified,eligible_for_acquisition,evidence_json,evidence_sha256)
                VALUES (?,?,?,?,'VERIFIED',1,1,?,?)""",
                (nid,anidb,tvdb,source,evidence,hashlib.sha256(evidence.encode()).hexdigest()))
            db.execute("""INSERT INTO episode_verification_v16
                (notification_id,evaluated_at,decision,verified,evidence_json)
                VALUES (?,?,'VERIFIED',1,?)""", (nid,time.time(),evidence))
            db.execute("""INSERT INTO episode_approval_queue
                (notification_id,decision,season,episode)
                VALUES (?,'AUTO_APPROVED',?,?)""", (nid,season,episode))
            db.execute("""INSERT INTO episode_dispatch
                (notification_id,series_id,season,episode,state)
                VALUES (?,?,?,?,'CLAIMED')""", (nid,sid,season,episode))
            db.execute("""INSERT OR IGNORE INTO episodes(series_id,season,episode,status)
                VALUES (?,?,?,'ACQUIRING')""", (sid,season,episode))
        approved_dispatch(db, nid)
        ensure_schema(db)
        payload = json.dumps({"notification_id": nid, "infohash": infohash,
            "magnet_uri": magnet, "title": title, "tvdb_id": tvdb}, sort_keys=True)
        db.execute("""INSERT INTO daemon_jobs(kind,subject_key,payload_json,state)
            VALUES ('claimed_acquisition',?,?,'READY')""", (str(nid),payload))
        db.commit()
        return {"notification_id": nid, "queued": True, "duplicate": False, "series_id": sid}
    except BaseException:
        db.rollback()
        raise


def receive(db, values):
    """Accept Autobrr metadata. Repeat GUID+hash is idempotent."""
    if not isinstance(values,dict):
        raise ValueError("Expected webhook object")
    source = str(values.get("source") or "autobrr").strip()[:100]
    name = str(values.get("release_name") or values.get("torrentName") or values.get("name") or "").strip()
    infohash = str(values.get("info_hash") or values.get("torrentHash") or values.get("hash") or "").strip().lower()
    guid = str(values.get("source_guid") or values.get("guid") or infohash).strip()[:500]
    if not source or not name or not HASH.fullmatch(infohash) or not guid:
        raise ValueError("Release name and 40/64 character torrent hash required")
    auto_fields = ("tvdb_id","anidb_id","season","episode")
    auto = all(values.get(field) is not None and str(values[field]).strip() for field in auto_fields)
    if auto:
        _approval_values(values)
        _magnet(values.get("magnet_uri") or values.get("magnet"), infohash)
    if db.in_transaction:
        raise ValueError("Webhook requires autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        old = db.execute("""SELECT id,info_hash FROM notifications
            WHERE source=? AND source_guid=?""", (source,guid)).fetchone()
        if old and old[1].lower()!=infohash:
            raise ValueError("GUID already belongs to a different torrent")
        if old:
            nid = old[0]
        else:
            nid = db.execute("""INSERT INTO notifications
                (source,release_name,source_guid,info_hash,received_at)
                VALUES (?,?,?,?,?)""", (source,name,guid,infohash,int(time.time()))).lastrowid
        db.commit()
    except BaseException:
        db.rollback()
        raise
    result = {"received": True, "notification_id": nid, "duplicate": bool(old)}
    if auto:
        result.update(approve(db,nid,values,source="autobrr"))
    return result
