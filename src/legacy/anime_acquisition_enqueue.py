"""Explicitly queue an approved claimed episode for the opt-in daemon.

This does not enable the acquisition handler or contact qBittorrent.
"""
import json
from anime_acquisition_gate import approved_dispatch
from anime_async_daemon import ensure_schema

def enqueue_claimed_acquisition(db, notification_id, *, infohash, magnet_uri,
                                title, tvdb_id):
    if db.in_transaction:
        raise ValueError("Autocommit required")
    if type(notification_id) is not int or notification_id<=0:
        raise ValueError("Invalid notification")
    if not isinstance(infohash,str) or len(infohash) not in (40,64) or any(
            ch not in "0123456789abcdef" for ch in infohash.lower()):
        raise ValueError("Invalid torrent hash")
    if not isinstance(magnet_uri,str) or not magnet_uri.startswith("magnet:?"):
        raise ValueError("Invalid magnet")
    if not isinstance(title,str) or not title.strip():
        raise ValueError("Missing title")
    if not str(tvdb_id).isdigit() or int(tvdb_id)<=0:
        raise ValueError("Invalid TVDB identity")
    db.execute("BEGIN IMMEDIATE")
    try:
        approved_dispatch(db,notification_id)
        row=db.execute("SELECT info_hash FROM notifications WHERE id=?",
                       (notification_id,)).fetchone()
        bound=db.execute("SELECT tvdb_id FROM verified_series_identity WHERE notification_id=?",
                         (notification_id,)).fetchone()
        if (not row or str(row[0]).lower()!=infohash.lower() or
                not bound or str(bound[0])!=str(tvdb_id)):
            raise ValueError("Claim identity mismatch")
        payload=json.dumps({"notification_id":notification_id,"infohash":infohash.lower(),
            "magnet_uri":magnet_uri,"title":title,"tvdb_id":tvdb_id},sort_keys=True)
        ensure_schema(db)
        existing=db.execute("""SELECT payload_json FROM daemon_jobs
            WHERE kind='claimed_acquisition' AND subject_key=?""",
            (str(notification_id),)).fetchone()
        if existing and existing[0]!=payload:
            raise ValueError("Conflicting acquisition job")
        if not existing:
            db.execute("""INSERT INTO daemon_jobs(kind,subject_key,payload_json,state)
                VALUES ('claimed_acquisition',?,?,'READY')""",
                (str(notification_id),payload))
        db.commit()
        return not bool(existing)
    except BaseException:
        db.rollback()
        raise
