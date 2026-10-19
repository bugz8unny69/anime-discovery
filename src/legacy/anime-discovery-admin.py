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
import subprocess
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
    parser=argparse.ArgumentParser(prog="anime-discovery-admin.py",
        description="Manage Anime Discovery releases, database and flat-file settings.")
    parser.add_argument("--config-dir",type=Path,default=DEFAULT_CONFIG)
    parser.add_argument("--db",type=Path,default=None,
                        help="Override configured database path for local administration")
    commands=parser.add_subparsers(dest="command",required=True)

    upgrade_cmd=commands.add_parser("upgrade",help="Upgrade Git checkout or extracted release archive")
    upgrade_cmd.add_argument("archive",nargs="?",type=Path,help="Downloaded release tar.gz for archive installations")
    upgrade_cmd.add_argument("--verbose",action="store_true",help="Show upgrade milestones and service readiness checks")
    upgrade_cmd.add_argument("--backup",action="store_true",help="Keep code and database backups after successful archive upgrade")
    commands.add_parser("status",help="Show installed version, service and database readiness")

    database=commands.add_parser("database",help="Database administration")
    database_actions=database.add_subparsers(dest="database_command",required=True)
    init=database_actions.add_parser("init",help="Create the application database")
    init.add_argument("--force",action="store_true",help="Replace with backup (service must be stopped)")
    database_actions.add_parser("doctor",help="Check SQLite schema and integrity")

    settings=commands.add_parser("settings",help="Flat-file settings")
    settings_actions=settings.add_subparsers(dest="settings_command",required=True)
    show_cmd=settings_actions.add_parser("show")
    show_cmd.add_argument("--json",action="store_true")
    secret_cmd=settings_actions.add_parser("set-secret")
    secret_cmd.add_argument("key")
    secret_cmd.add_argument("--clear",action="store_true")
    settings_actions.add_parser("configure-credentials",help="Set separate webhook token and dashboard password")
    settings_actions.add_parser("configure-jellyfin",help="Configure immediate Jellyfin library scan credentials")
    integration=settings_actions.add_parser("configure-integration",help="Configure Sonarr, NTFY, TVDB or Shoko")
    integration.add_argument("service",choices=("sonarr","ntfy","tvdb","shoko"))
    settings_actions.add_parser("probe-shoko",help="Read-only Shoko connection probe")
    migration=settings_actions.add_parser("migrate",help="Preview or apply missing settings to existing JSON files")
    migration.add_argument("--apply",action="store_true",help="Back up settings.json and add missing settings")
    set_cmd=settings_actions.add_parser("set")
    set_cmd.add_argument("key")
    set_cmd.add_argument("value",help="JSON value, e.g. 5, true, or quoted string")

    # Preserve existing scripts while presenting one consistent grouped CLI.
    commands.add_parser("doctor",help=argparse.SUPPRESS)
    legacy_init=commands.add_parser("new-database",help=argparse.SUPPRESS)
    legacy_init.add_argument("--force",action="store_true")

    args=parser.parse_args(argv)
    try:
        if args.command=="upgrade":
            from anime_admin_upgrade import upgrade
            config=load_config(args.config_dir)
            configured_db=Path(config["settings"]["daemon"]["database_path"])
            root=Path(__file__).resolve().parents[2]
            if args.archive is not None:
                from anime_admin_archive_upgrade import upgrade_archive
                result=upgrade_archive(root,args.archive,db_path=args.db or configured_db,
                    verbose=args.verbose,backup=args.backup,log=lambda message: print(message,file=sys.stderr,flush=True))
            else:
                if not (root/".git").exists():
                    raise ValueError("Archive installation: download the new release tar.gz and pass its local path to upgrade")
                result=upgrade(root,db_path=args.db or configured_db,
                    verbose=args.verbose,log=lambda message: print(message,file=sys.stderr,flush=True))
            print(json.dumps(result,indent=2,sort_keys=True))
        elif args.command=="status":
            from anime_admin_upgrade import command
            root=Path(__file__).resolve().parents[2]
            config=load_config(args.config_dir)
            path=args.db or Path(config["settings"]["daemon"]["database_path"])
            version=(command("git","rev-parse","--short","HEAD",cwd=root)
                     if (root/".git").exists() else "archive installation")
            report={"checkout":str(root),"version":version,
                    "database":doctor(path)}
            try:
                report["service"]=command("systemctl","is-active","anime-discovery.service")
            except subprocess.CalledProcessError:
                report["service"]="inactive"
            print(json.dumps(report,indent=2,sort_keys=True))
        elif args.command in ("new-database","database") and (
            args.command=="new-database" or args.database_command=="init"):
            config=load_config(args.config_dir)
            path=args.db or Path(config["settings"]["daemon"]["database_path"])
            result=new_database(path,force=args.force)
            print(f"Initialized database at {path}; schema version {result['schema_version']}.")
        elif args.command=="doctor" or (args.command=="database" and args.database_command=="doctor"):
            path=args.db
            if path is None:
                path=Path(load_config(args.config_dir)["settings"]["daemon"]["database_path"])
            report=doctor(path)
            print(json.dumps(report,indent=2,sort_keys=True))
            if not report["ready"]:
                parser.exit(1,"anime-discovery-admin: database readiness failed\\n")
        elif args.command=="settings":
            if args.settings_command=="configure-jellyfin":
                from anime_admin_jellyfin import configure_jellyfin
                print(json.dumps(configure_jellyfin(args.config_dir),indent=2))
            elif args.settings_command=="configure-integration":
                from anime_admin_integrations import configure
                print(json.dumps(configure(args.config_dir,args.service),indent=2))
            elif args.settings_command=="probe-shoko":
                from anime_shoko_probe import inspect_shoko
                cfg=load_config(args.config_dir)["settings"]["shoko"]
                result=inspect_shoko(cfg["base_url"])
                print(json.dumps({"reachable":result["reachable"],"writes_enabled":False},indent=2))
            elif args.settings_command=="configure-credentials":
                from anime_admin_credentials import configure_credentials
                report=configure_credentials(args.config_dir)
                from anime_admin_secret_editor import set_secret
                from anime_flat_config import ALLOWED_SECRET_KEYS
                report["supported_credential_status"]={}
                for name in sorted(ALLOWED_SECRET_KEYS-{"web_token","admin_password"}):
                    outcome=set_secret(args.config_dir,name)
                    report["supported_credential_status"][name]=outcome.get("status",
                        "Set" if load_config(args.config_dir)["secrets"].get(name) else "Not set")
                    if outcome.get("changed"):
                        report["restart_required"]=True
                print(json.dumps(report,indent=2))
            elif args.settings_command=="migrate":
                from anime_admin_config_migration import migrate
                print(json.dumps(migrate(args.config_dir,apply=args.apply),indent=2,sort_keys=True))
            elif args.settings_command=="show":
                from anime_admin_show import render
                print(render(args.config_dir,as_json=args.json))
            elif args.settings_command=="set-secret":
                from anime_admin_secret_editor import set_secret
                print(json.dumps(set_secret(args.config_dir,args.key,clear=args.clear),indent=2))
            else:
                try:
                    value=json.loads(args.value)
                except json.JSONDecodeError:
                    value=args.value
                updated=set_setting(args.config_dir,args.key,value)
                print(f"{args.key} = {json.dumps(updated)} (restart service to apply)")
    except (OSError,ValueError,sqlite3.Error,RuntimeError,subprocess.CalledProcessError) as exc:
        parser.exit(1,f"anime-discovery-admin: {exc}\\n")

if __name__=="__main__":
    main()
