"""Offline evidence import for a unified SQLite database.

Import stable snapshots only. Conflicts and missing notification IDs abort
the whole transaction. No worker, torrent, or service is touched.
"""
import sqlite3
from pathlib import Path

TABLES={
 "verified_series_identity": ("notification_id","anidb_id","tvdb_id","mapping_source","decision","episode_identity_verified","eligible_for_acquisition","evidence_json","evidence_sha256","created_at","updated_at"),
 "confidence_shadow_v15": ("notification_id","evaluated_at","policy_version","score","decision","evidence_json"),
 "episode_verification_v16": ("notification_id","evaluated_at","decision","verified","evidence_json"),
}
SCHEMAS={
 "verified_series_identity": """CREATE TABLE IF NOT EXISTS verified_series_identity (
 notification_id INTEGER PRIMARY KEY, anidb_id TEXT NOT NULL,tvdb_id TEXT NOT NULL,
 mapping_source TEXT NOT NULL,decision TEXT NOT NULL,
 episode_identity_verified INTEGER NOT NULL CHECK(episode_identity_verified=0),
 eligible_for_acquisition INTEGER NOT NULL CHECK(eligible_for_acquisition=0),
 evidence_json TEXT NOT NULL,evidence_sha256 TEXT NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""",
 "confidence_shadow_v15": """CREATE TABLE IF NOT EXISTS confidence_shadow_v15 (
 notification_id INTEGER PRIMARY KEY,evaluated_at REAL NOT NULL,
 policy_version TEXT NOT NULL,score INTEGER NOT NULL,decision TEXT NOT NULL,
 evidence_json TEXT NOT NULL)""",
 "episode_verification_v16": """CREATE TABLE IF NOT EXISTS episode_verification_v16 (
 notification_id INTEGER PRIMARY KEY,evaluated_at REAL NOT NULL,
 decision TEXT NOT NULL,verified INTEGER NOT NULL,evidence_json TEXT NOT NULL)""",
}

def snapshot(path, table):
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True) as db:
        if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Source integrity failure")
        columns=TABLES[table]
        present={r[1] for r in db.execute("PRAGMA table_info("+table+")")}
        if not set(columns)<=present:
            raise ValueError("Unexpected source schema: "+table)
        return db.execute("SELECT "+",".join(columns)+" FROM "+table).fetchall()

def import_evidence(db, verified_path, shadow_path):
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    sources={"verified_series_identity":verified_path,
             "confidence_shadow_v15":shadow_path,"episode_verification_v16":shadow_path}
    rows={table:snapshot(path,table) for table,path in sources.items()}
    db.execute("BEGIN IMMEDIATE")
    try:
        ids={r[0] for r in db.execute("SELECT id FROM notifications")}
        for table,records in rows.items():
            db.execute(SCHEMAS[table])
            cols=TABLES[table]
            for record in records:
                if record[0] not in ids:
                    raise ValueError("Evidence references missing notification")
                existing=db.execute("SELECT "+",".join(cols)+" FROM "+table+" WHERE notification_id=?",(record[0],)).fetchone()
                if existing is not None and existing!=record:
                    raise ValueError("Conflicting imported evidence: "+table)
                if existing is None:
                    db.execute("INSERT INTO "+table+"("+",".join(cols)+") VALUES ("+",".join("?" for _ in cols)+")",record)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {table:len(records) for table,records in rows.items()}
