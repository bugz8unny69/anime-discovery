"""Anime Discovery administration CLI.

Configuration is flat JSON. Database initialization is explicit and refuses
to replace existing files. No service restart or deployment is performed.
"""
import argparse
from contextlib import closing
import json
import os
import sqlite3
import sys
from pathlib import Path

from anime_admin_settings import set_setting
from anime_flat_config import load_config
from anime_async_daemon import ensure_schema as ensure_jobs
from anime_series_cache import ensure_schema as ensure_cache

DEFAULT_DB=Path("/var/lib/anime-discovery/anime-discovery.db")
DEFAULT_CONFIG=Path("/etc/anime-discovery")

def new_database(path, *, force=False):
    """Initialize from scratch; forced reset retains an offline safety backup."""
    from anime_fresh_database import initialize
    path=Path(path)
    if not force or not path.exists():
        return initialize(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("Force requires a regular database, not a symlink")
    if any(Path(str(path)+suffix).exists() for suffix in ("-wal","-shm","-journal")):
        raise ValueError("SQLite sidecar exists: stop services and checkpoint before --force")
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=rw",uri=True,timeout=0,isolation_level=None)) as db:
        db.execute("BEGIN EXCLUSIVE")
        db.execute("ROLLBACK")
    backup=Path(str(path)+".pre-force-backup")
    if backup.exists() or backup.is_symlink():
        raise FileExistsError("Safety backup already exists: "+str(backup))
    path.rename(backup)
    try:
        return initialize(path)
    except BaseException:
        path.unlink(missing_ok=True)
        backup.rename(path)
        raise

def doctor(path):
    """Read-only fresh-install database readiness report; never starts workers."""
    path=Path(path)
    if not path.is_file() or path.is_symlink():
        raise FileNotFoundError("Database not found or not a regular file: "+str(path))
    with closing(sqlite3.connect(path.resolve().as_uri()+"?mode=ro",
                                 uri=True,isolation_level=None,timeout=5)) as db:
        version=db.execute("SELECT version FROM schema_version").fetchone()
        if version is None or version[0]!=1:
            raise ValueError("Unsupported fresh database schema")
        integrity=db.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys=db.execute("PRAGMA foreign_key_check").fetchall()
        required=("series","episodes","notifications","verified_series_identity",
                  "episode_approval_queue","episode_dispatch","daemon_jobs",
                  "torrent_recovery_records","external_actions","verified_series_cache",
                  "series_quarantine","series_rejection_blocks")
        present={row[0] for row in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        missing=sorted(set(required)-present)
        jobs=db.execute("SELECT state,count(*) FROM daemon_jobs GROUP BY state").fetchall() if "daemon_jobs" in present else []
        result={"schema_version":version[0],"integrity":integrity,
                "foreign_key_violations":len(foreign_keys),
                "missing_tables":missing,"jobs":dict(jobs)}
        result["ready"]=(integrity=="ok" and not foreign_keys and not missing)
        return result


def main(argv=None):
    parser=argparse.ArgumentParser(prog="anime-discovery-admin.py")
    parser.add_argument("--config-dir",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--db",type=Path,default=DEFAULT_DB)
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("doctor")
    new_db=commands.add_parser("new-database")
    new_db.add_argument("--force",action="store_true")
    settings=commands.add_parser("settings")
    sub=settings.add_subparsers(dest="settings_command",required=True)
    sub.add_parser("show")
    set_cmd=sub.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value",help="JSON value, e.g. 5, true, or quoted string")
    args=parser.parse_args(argv)
    try:
        if args.command=="new-database":
            result=new_database(args.db,force=args.force)
            print(f"Initialized fresh database at {args.db}; schema version {result['schema_version']}; acquisition disabled.")
        elif args.command=="doctor":
            report=doctor(args.db)
            print(json.dumps(report,indent=2,sort_keys=True))
            if not report["ready"]:
                parser.exit(1,"anime-discovery-admin: database readiness failed\\n")
        elif args.settings_command=="show":
            print(json.dumps(load_config(args.config_dir)["settings"],indent=2,sort_keys=True))
        else:
            try:
                value=json.loads(args.value)
            except json.JSONDecodeError:
                value=args.value
            updated=set_setting(args.config_dir,args.key,value)
            print(f"{args.key} = {json.dumps(updated)} (daemon reload pending)")
    except (OSError,ValueError,sqlite3.Error,RuntimeError) as exc:
        parser.exit(1,f"anime-discovery-admin: {exc}\n")

if __name__=="__main__":
    main()
