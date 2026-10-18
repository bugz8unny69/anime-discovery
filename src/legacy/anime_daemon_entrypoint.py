"""Safe daemon entrypoint using flat-file configuration.

No production handlers are registered yet: fail closed rather than silently
acknowledging work or triggering downloads before integrations are verified.
"""
import argparse
import asyncio
import sqlite3
from pathlib import Path

from anime_flat_config import load_config
from anime_config_reload import ConfigManager
from anime_async_daemon import ensure_schema, run_workers
from anime_safe_handlers import SAFE_HANDLERS
from anime_migration_preflight import preflight


def configured_daemon(config_dir, db_path, handlers):
    config=load_config(config_dir)
    if not handlers:
        raise RuntimeError("No verified daemon handlers registered; refusing to start")
    for name, handler in handlers.items():
        if not isinstance(name,str) or not callable(handler):
            raise ValueError("Invalid handler registration")
    if not Path(db_path).is_file():
        raise FileNotFoundError(
            f"Anime Discovery database not found: {db_path}\\n"
            "Initialize it with: anime-discovery-admin.py new-database\\n"
            "No database was created automatically.")
    with sqlite3.connect(f"file:{Path(db_path).resolve()}?mode=rw",
                         uri=True,isolation_level=None,timeout=10) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        ensure_schema(db)
    manager=ConfigManager(config_dir)
    # Initial settings are validated before the worker pool is started.
    # Workers refresh snapshots at job boundaries, never during a handler.
    return run_workers(str(db_path),handlers,
                       concurrency=config["settings"]["daemon"]["concurrency"],
                       config_manager=manager)


def main(argv=None):
    parser=argparse.ArgumentParser()
    parser.add_argument("--config-dir",default="/etc/anime-discovery")
    parser.add_argument("--db",default="/var/lib/anime-discovery/anime-discovery.db")
    parser.add_argument("--read-only-preflight",action="store_true",help="Only run non-mutating preflight jobs")
    args=parser.parse_args(argv)
    if not args.read_only_preflight:
        raise RuntimeError("Write-capable handlers are not validated; use --read-only-preflight")
    # Preflight is intentionally read-only. Refuse incomplete migration
    # before starting a scheduler that could create its own job schema.
    result=preflight(args.db)
    if not result["ready"]:
        raise RuntimeError("Unified database migration incomplete: "+str(result))
    asyncio.run(configured_daemon(args.config_dir,args.db,SAFE_HANDLERS))


if __name__=="__main__":
    main()
