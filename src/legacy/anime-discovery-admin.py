"""Anime Discovery administration CLI.

Configuration is flat JSON. Database initialization is explicit and refuses
to replace existing files. No service restart or deployment is performed.
"""
import argparse
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

def new_database(path):
    path=Path(path)
    if not path.parent.is_dir():
        raise FileNotFoundError(f"Database parent directory does not exist: {path.parent}")
    fd=os.open(path,os.O_CREAT | os.O_EXCL | os.O_RDWR,0o600)
    os.close(fd)
    try:
        with sqlite3.connect(path,isolation_level=None) as db:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA journal_mode=WAL")
            # Only initialize schemas independent of legacy controller tables.
            # A new DB is NOT marked production-ready until controller schema
            # and migrations are applied.
            ensure_jobs(db)
            ensure_cache(db)
            db.execute("""CREATE TABLE IF NOT EXISTS schema_bootstrap (
                id INTEGER PRIMARY KEY CHECK(id=1),
                status TEXT NOT NULL CHECK(status='PENDING_MIGRATIONS')
            )""")
            db.execute("INSERT INTO schema_bootstrap VALUES(1,'PENDING_MIGRATIONS')")
            if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                raise RuntimeError("Database integrity check failed")
    except BaseException:
        # Never erase a file created by another process after initialization.
        # This path is ours, created with O_EXCL.
        for suffix in ("-wal","-shm",""):
            (Path(str(path)+suffix)).unlink(missing_ok=True)
        raise
    return path

def main(argv=None):
    parser=argparse.ArgumentParser(prog="anime-discovery-admin.py")
    parser.add_argument("--config-dir",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--db",type=Path,default=DEFAULT_DB)
    commands=parser.add_subparsers(dest="command",required=True)
    commands.add_parser("new-database")
    settings=commands.add_parser("settings")
    sub=settings.add_subparsers(dest="settings_command",required=True)
    sub.add_parser("show")
    set_cmd=sub.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value",help="JSON value, e.g. 5, true, or quoted string")
    args=parser.parse_args(argv)
    try:
        if args.command=="new-database":
            print(f"Initialized database bootstrap at {new_database(args.db)}; migrations still required.")
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
