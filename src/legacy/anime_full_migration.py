"""Offline-only migration orchestration.

Merge legacy controller/inbox snapshots, then import V8/V15/V16 evidence.
Never switches a service or mutates source databases.
"""
import argparse
import sqlite3
from pathlib import Path

from unified_migration import merge
from anime_unified_evidence_import import import_evidence


def migrate(controller, inbox, verified, shadow, output):
    paths=[Path(p).resolve() for p in (controller,inbox,verified,shadow,output)]
    if len(set(paths))!=len(paths):
        raise ValueError("All source and destination paths must be distinct")
    result=merge(paths[0],paths[1],paths[4])
    try:
        with sqlite3.connect(paths[4],isolation_level=None,timeout=10) as db:
            db.execute("PRAGMA busy_timeout=10000")
            result["evidence"]=import_evidence(db,paths[2],paths[3])
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise ValueError("Output integrity check failed")
        return result
    except BaseException:
        # Destination was created by merge, never remove source snapshots.
        for suffix in ("-wal","-shm",""):
            Path(str(paths[4])+suffix).unlink(missing_ok=True)
        raise


def main(argv=None):
    parser=argparse.ArgumentParser(description="Offline migration rehearsal; services unchanged")
    for name in ("controller","inbox","verified","shadow","output"):
        parser.add_argument("--"+name,type=Path,required=True)
    parser.add_argument("--confirm-offline",action="store_true")
    args=parser.parse_args(argv)
    if not args.confirm_offline:
        parser.error("Explicit --confirm-offline required; use stable source snapshots")
    print(migrate(args.controller,args.inbox,args.verified,args.shadow,args.output))


if __name__=="__main__":
    main()
