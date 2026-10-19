"""Update an installed Anime Discovery checkout from the release branch.

No environment variables or worker switches. The VM service is restarted
once per upgrade. The SQLite backup uses the SQLite backup API rather than
copying an active database file.
"""
from datetime import datetime, timezone
from pathlib import Path
import os
import pwd
import sqlite3
import subprocess


def command(*args, cwd=None):
    if args and args[0]=="git" and cwd is not None:
        owner_id=Path(cwd).stat().st_uid
        if os.geteuid()==0 and owner_id!=0:
            owner=pwd.getpwuid(owner_id).pw_name
            args=("runuser","-u",owner,"--",*args)
        else:
            args=("git","-c","safe.directory="+str(Path(cwd).resolve()),*args[1:])
    return subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=True).stdout.strip()


def _version(root):
    return command("git", "rev-parse", "HEAD", cwd=root)


def upgrade(root, *, service="anime-discovery.service", branch="develop", db_path=None,
            service_manager="systemctl", runner=command):
    """Fast-forward only, SQLite backup, service restart, read-only DB check.

    No database restoration is attempted automatically if an upgrade fails;
    the dated backup remains for a deliberate rollback if a future schema
    migration has taken place. An unsuccessful restart restores the previous
    Git commit and retries the prior service.
    """
    root=Path(root).resolve()
    if not (root/".git").exists():
        raise ValueError("Upgrade requires a Git checkout")
    if runner("git","status","--porcelain",cwd=root):
        raise ValueError("Checkout has local changes; upgrade requires a clean worktree")
    current_branch=runner("git","branch","--show-current",cwd=root)
    if current_branch!=branch:
        raise ValueError("Upgrade requires the deployed "+branch+" branch (found "+current_branch+")")
    previous=runner("git","rev-parse","HEAD",cwd=root)
    runner("git","fetch","origin",branch,cwd=root)
    latest=runner("git","rev-parse","FETCH_HEAD",cwd=root)
    if latest==previous:
        return {"updated":False,"version":previous,"backup":None}
    merge_base=runner("git","merge-base",previous,latest,cwd=root)
    if merge_base!=previous:
        raise ValueError("Remote release cannot be fast-forwarded")
    backup=None
    if db_path is not None:
        db_path=Path(db_path)
        if not db_path.is_file() or db_path.is_symlink():
            raise ValueError("Configured database not found")
        date=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup=Path(str(db_path)+".before-"+date+"-"+previous[:8]+".bak")
        if backup.exists():
            raise FileExistsError("Backup already exists: "+str(backup))
        # Online-safe backup, made before the service is stopped.
        with sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",uri=True,timeout=15) as src:
            with sqlite3.connect(backup) as dst:
                src.backup(dst)
                if dst.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise ValueError("SQLite backup failed integrity check")
        backup.chmod(0o600)
    stopped=False
    advanced=False
    try:
        runner(service_manager,"stop",service)
        stopped=True
        runner("git","merge","--ff-only","FETCH_HEAD",cwd=root)
        advanced=True
        # No schema migration in version 1. Refuse starting against an unknown version.
        if db_path is not None:
            with sqlite3.connect(Path(db_path).resolve().as_uri()+"?mode=ro",uri=True,timeout=10) as db:
                row=db.execute("SELECT version FROM schema_version").fetchone()
                if row is None or row[0]!=1:
                    raise ValueError("Unsupported database schema; original backup preserved")
                if db.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                    raise ValueError("Database failed integrity check")
        runner(service_manager,"start",service)
        runner(service_manager,"is-active","--quiet",service)
    except BaseException:
        if advanced:
            # Only rewind Git if the checkout is exactly the version we moved to.
            if runner("git","rev-parse","HEAD",cwd=root)==latest:
                runner("git","reset","--hard",previous,cwd=root)
        if stopped:
            try:
                runner(service_manager,"start",service)
            except Exception:
                pass
        raise
    return {"updated":True,"previous":previous,"version":latest,
            "backup":str(backup) if backup else None}
