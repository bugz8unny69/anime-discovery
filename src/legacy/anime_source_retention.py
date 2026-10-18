"""Persist torrent recovery details without deleting the original media.

Source cleanup is a separate explicitly authorized operation. This module
only creates an auditable recovery record after staged media verification.
"""
import hashlib
import json
import sqlite3
import time
from pathlib import Path
from anime_audio_verification import confirmed_jp_en

def retain_recovery_record(db, *, infohash, magnet_uri, source, staged, notification_id):
    source=Path(source)
    staged=Path(staged)
    if not source.is_file() or source.is_symlink() or not staged.is_file() or staged.is_symlink():
        raise ValueError("Missing or unsafe media")
    if source.resolve()==staged.resolve():
        raise ValueError("Source and staged media must differ")
    if source.stat().st_size!=staged.stat().st_size:
        raise ValueError("Staged media size differs from source")
    if not confirmed_jp_en(staged):
        raise ValueError("Japanese and English audio not confirmed")
    digest=hashlib.sha256()
    with staged.open("rb") as f:
        for chunk in iter(lambda:f.read(1024*1024),b""):
            digest.update(chunk)
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS torrent_recovery_records (
            notification_id INTEGER PRIMARY KEY,
            infohash TEXT NOT NULL,
            magnet_uri TEXT NOT NULL,
            staged_path TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            recorded_at INTEGER NOT NULL)""")
        existing=db.execute("SELECT infohash,magnet_uri,staged_path,sha256 FROM torrent_recovery_records WHERE notification_id=?",
                            (notification_id,)).fetchone()
        record=(infohash,magnet_uri,str(staged.resolve()),digest.hexdigest())
        if existing and existing!=record:
            raise ValueError("Conflicting recovery record")
        if not existing:
            db.execute("INSERT INTO torrent_recovery_records VALUES (?,?,?,?,?,?)",
                       (notification_id,*record,int(time.time())))
        db.commit()
        return {"eligible_for_cleanup_review":True,"sha256":digest.hexdigest()}
    except BaseException:
        db.rollback()
        raise
