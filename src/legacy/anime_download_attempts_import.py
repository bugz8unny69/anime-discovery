"""Preserve observed controller download attempts as inactive legacy history.

The source table has five rows in the reviewed snapshot. No acquisition,
retry, or dispatch is enabled by importing this historical evidence.
"""
import sqlite3
from pathlib import Path

COLUMNS=("id","series_id","season","episode","torrent_hash","release_title",
         "status","progress","last_progress_at","created_at","updated_at")
SCHEMA="""CREATE TABLE IF NOT EXISTS legacy_download_attempts (
 id INTEGER PRIMARY KEY,
 series_id INTEGER NOT NULL,
 season INTEGER NOT NULL,
 episode INTEGER NOT NULL,
 torrent_hash TEXT NOT NULL UNIQUE,
 release_title TEXT NOT NULL,
 status TEXT NOT NULL DEFAULT 'QUEUED',
 progress REAL NOT NULL DEFAULT 0,
 last_progress_at TEXT,
 created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
 updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
)"""

def import_download_attempts(db, source_path):
    if db.in_transaction:
        raise ValueError("Autocommit destination required")
    path=Path(source_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Safe controller snapshot required")
    destination=db.execute("PRAGMA database_list").fetchone()[2]
    if not destination or Path(destination).resolve()==path.resolve():
        raise ValueError("Distinct on-disk destination required")
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Source integrity failure")
        expected=[("id","INTEGER",0,1),("series_id","INTEGER",1,0),
                  ("season","INTEGER",1,0),("episode","INTEGER",1,0),
                  ("torrent_hash","TEXT",1,0),("release_title","TEXT",1,0),
                  ("status","TEXT",1,0),("progress","REAL",1,0),
                  ("last_progress_at","TEXT",0,0),("created_at","TEXT",1,0),
                  ("updated_at","TEXT",1,0)]
        actual=[(r[1],r[2].upper(),r[3],r[5]) for r in src.execute(
            "PRAGMA table_info(download_attempts)")]
        if actual!=expected:
            raise ValueError("Unrecognized download attempts schema")
        rows=src.execute("SELECT "+",".join(COLUMNS)+" FROM download_attempts").fetchall()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(SCHEMA)
        actual=[(r[1],r[2].upper(),r[3],r[5]) for r in db.execute(
            "PRAGMA table_info(legacy_download_attempts)")]
        if actual!=expected:
            raise ValueError("Conflicting destination attempts schema")
        current=db.execute("SELECT "+",".join(COLUMNS)+
                           " FROM legacy_download_attempts").fetchall()
        if current and sorted(current)!=sorted(rows):
            raise ValueError("Conflicting destination attempt history")
        if not current:
            db.executemany("INSERT INTO legacy_download_attempts("+",".join(COLUMNS)+
                           ") VALUES ("+",".join("?" for _ in COLUMNS)+")",rows)
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key failure")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"historical_rows":len(rows),"acquisition_enabled":False,"source_modified":False}
