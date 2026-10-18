"""Offline import of the observed V10 identity queue.

Preserves pending retry state as historical data; does not reactivate workers.
Requires a separately reviewed source snapshot and a new destination table.
"""
import sqlite3
from pathlib import Path

SCHEMA="""CREATE TABLE legacy_identity_queue_v10 (
 notification_id INTEGER PRIMARY KEY,
 last_action TEXT NOT NULL,
 attempts INTEGER NOT NULL,
 next_at REAL NOT NULL,
 updated_at REAL NOT NULL
)"""
COLUMNS=("notification_id","last_action","attempts","next_at","updated_at")

def import_identity_queue_v10(db, source_path):
    if db.in_transaction:
        raise ValueError("Autocommit destination required")
    path=Path(source_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Safe V10 snapshot required")
    destination=db.execute("PRAGMA database_list").fetchone()[2]
    if not destination or Path(destination).resolve()==path.resolve():
        raise ValueError("Distinct on-disk destination required")
    with sqlite3.connect(path.resolve().as_uri()+"?mode=ro",uri=True) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Source integrity failure")
        expected=[("notification_id","INTEGER",0,1),("last_action","TEXT",1,0),
                  ("attempts","INTEGER",1,0),("next_at","REAL",1,0),
                  ("updated_at","REAL",1,0)]
        actual=[(r[1],r[2].upper(),r[3],r[5]) for r in src.execute(
            "PRAGMA table_info(identity_queue)")]
        if actual!=expected:
            raise ValueError("Unrecognized V10 identity queue schema")
        rows=src.execute("SELECT "+",".join(COLUMNS)+" FROM identity_queue").fetchall()
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute(SCHEMA.replace("CREATE TABLE ","CREATE TABLE IF NOT EXISTS ",1))
        present=[(r[1],r[2].upper(),r[3],r[5]) for r in db.execute(
            "PRAGMA table_info(legacy_identity_queue_v10)")]
        if present!=expected:
            raise ValueError("Conflicting destination queue schema")
        existing=db.execute("SELECT "+",".join(COLUMNS)+
                            " FROM legacy_identity_queue_v10").fetchall()
        if existing and sorted(existing)!=sorted(rows):
            raise ValueError("Conflicting destination queue state")
        if not existing:
            db.executemany("INSERT INTO legacy_identity_queue_v10 VALUES (?,?,?,?,?)",rows)
        if db.execute("PRAGMA foreign_key_check").fetchall():
            raise ValueError("Foreign key failure")
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"imported_rows":len(rows),"queue_activated":False,"source_modified":False}
