"""Offline-only SQLite merger. Does not modify legacy databases or switch services."""
import argparse
import sqlite3
import time
from pathlib import Path

def _check(db):
    if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        raise ValueError("SQLite integrity failure")

def _columns(db, table, expected):
    actual = {r[1] for r in db.execute("PRAGMA table_info("+table+")")}
    if not set(expected).issubset(actual):
        raise ValueError("Unexpected "+table+" schema")

def merge(controller, inbox, output):
    controller, inbox, output = map(lambda p: Path(p).resolve(), (controller, inbox, output))
    if len({controller, inbox, output}) != 3 or not controller.is_file() or not inbox.is_file():
        raise ValueError("Two distinct existing source databases required")
    if output.exists() or not output.parent.is_dir():
        raise ValueError("Output must not exist and parent must exist")
    created = False
    try:
        with sqlite3.connect(controller.as_uri()+"?mode=ro", uri=True) as source:
            _check(source)
            db = sqlite3.connect(output)
            created = True
            try:
                source.backup(db)
            finally:
                db.close()
        with sqlite3.connect(inbox.as_uri()+"?mode=ro", uri=True) as source:
            _check(source)
            _columns(source, "notifications", ("id","source","release_name","source_guid","info_hash","received_at","status"))
            notifications = source.execute("SELECT id,source,release_name,source_guid,info_hash,received_at,status FROM notifications ORDER BY id").fetchall()
        with sqlite3.connect(output) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            _columns(db, "series", ("id","source","external_id","title","status"))
            _columns(db, "episodes", ("series_id","season","episode","status"))
            db.execute("BEGIN IMMEDIATE")
            db.execute('CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY,source TEXT NOT NULL,release_name TEXT NOT NULL,source_guid TEXT NOT NULL,info_hash TEXT NOT NULL,received_at INTEGER NOT NULL,status TEXT NOT NULL DEFAULT "UNTRUSTED",UNIQUE(source,source_guid))')
            db.execute("CREATE TABLE IF NOT EXISTS migration_quarantined_series (series_id INTEGER PRIMARY KEY REFERENCES series(id),reason TEXT NOT NULL,quarantined_at INTEGER NOT NULL)")
            db.execute("CREATE TABLE IF NOT EXISTS migration_audit (id INTEGER PRIMARY KEY,source TEXT NOT NULL,record_count INTEGER NOT NULL,created_at INTEGER NOT NULL)")
            db.executemany("INSERT INTO notifications(id,source,release_name,source_guid,info_hash,received_at,status) VALUES (?,?,?,?,?,?,?)", notifications)
            now = int(time.time())
            db.execute("INSERT INTO migration_quarantined_series SELECT id,?,? FROM series WHERE lower(source)='test'", ("TEST_FIXTURE",now))
            series = db.execute("SELECT count(*) FROM series").fetchone()[0]
            quarantined = db.execute("SELECT count(*) FROM migration_quarantined_series").fetchone()[0]
            db.executemany("INSERT INTO migration_audit(source,record_count,created_at) VALUES (?,?,?)", (("controller_series",series,now),("inbox_notifications",len(notifications),now)))
            if db.execute("PRAGMA foreign_key_check").fetchall():
                raise ValueError("Foreign key check failed")
            db.commit()
            _check(db)
            return {"series":series,"notifications":len(notifications),"quarantined":quarantined}
    except BaseException:
        if created:
            output.unlink(missing_ok=True)
            for suffix in ("-wal","-shm"):
                Path(str(output)+suffix).unlink(missing_ok=True)
        raise

def main():
    parser = argparse.ArgumentParser(description="Offline migration rehearsal only; does not switch running services")
    parser.add_argument("--controller",type=Path,required=True)
    parser.add_argument("--inbox",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--confirm-offline",action="store_true")
    args=parser.parse_args()
    if not args.confirm_offline:
        parser.error("Requires --confirm-offline and stable source snapshots")
    print(merge(args.controller,args.inbox,args.output))

if __name__=="__main__":
    main()
