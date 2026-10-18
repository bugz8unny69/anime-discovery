"""Read-only-source archive of reviewed job and trial history.

Archive tables are inert snapshots, not executable queues.
"""
import sqlite3
from pathlib import Path
from anime_legacy_archive_audit import reconcile_archive

GROUPS={
 "jobs":("episode_jobs","historical_candidates","historical_search_attempts","job_events","series_jobs"),
 "trial":("trial_events",),
}

def archive_tables(db, source_path, group):
    if group not in GROUPS or db.in_transaction:
        raise ValueError("Explicit reviewed group and autocommit required")
    source_path=Path(source_path)
    if not source_path.is_file() or source_path.is_symlink():
        raise ValueError("Safe snapshot required")
    target=db.execute("PRAGMA database_list").fetchone()[2]
    if not target or Path(target).resolve()==source_path.resolve():
        raise ValueError("Distinct destination required")
    prepared=[]
    with sqlite3.connect(source_path.resolve().as_uri()+"?mode=ro",uri=True) as src:
        if src.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
            raise ValueError("Source integrity failure")
        for name in GROUPS[group]:
            columns=src.execute('PRAGMA table_info("'+name+'")').fetchall()
            if not columns:
                raise ValueError("Missing reviewed source table: "+name)
            records=src.execute('SELECT * FROM "'+name+'"').fetchall()
            prepared.append((name,columns,records))
    db.execute("BEGIN IMMEDIATE")
    try:
        for name,columns,records in prepared:
            archive="legacy_"+name
            # Archive copies preserve column names and SQLite value types.
            # They intentionally do not reproduce active queue constraints.
            definitions=",".join('"'+row[1]+'" '+(row[2] or "BLOB") for row in columns)
            db.execute('CREATE TABLE IF NOT EXISTS "'+archive+'" ('+definitions+')')
            actual=[(r[1],r[2]) for r in db.execute('PRAGMA table_info("'+archive+'")')]
            if actual!=[(r[1],r[2] or "BLOB") for r in columns]:
                raise ValueError("Archive schema conflict: "+name)
            existing=db.execute('SELECT * FROM "'+archive+'"').fetchall()
            if existing and sorted(existing,key=repr)!=sorted(records,key=repr):
                raise ValueError("Archive record conflict: "+name)
            if not existing:
                db.executemany('INSERT INTO "'+archive+'" VALUES ('+
                               ','.join('?' for _ in columns)+')',records)
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"archived_rows":{name:len(rows) for name,_,rows in prepared},
            "jobs_activated":False,"source_modified":False}
