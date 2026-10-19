"""Upgrade an archive-based VM installation without Git, SSH or network access.

User supplies a trusted, checksum-verified GitHub release tar.gz on the VM.
The deployment code is exchanged atomically with rollback on failed service
restart. Existing /etc configuration and /var/lib database remain untouched.
"""
import os
import shutil
import sqlite3
import stat
import tarfile
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from anime_admin_upgrade import command


def _extract(archive, destination):
    """Restrict tar members to ordinary files beneath anime-discovery/."""
    if not Path(archive).is_file():
        raise FileNotFoundError(archive)
    total=0
    count=0
    with tarfile.open(archive,"r:gz") as source:
        members=source.getmembers()
        for member in members:
            parts=PurePosixPath(member.name).parts
            if not parts or parts[0]!="anime-discovery" or any(
                    part in ("..",".") for part in parts):
                raise ValueError("Archive has unsafe member path")
            if not (member.isfile() or member.isdir()):
                raise ValueError("Archive has unsupported links or special files")
            total+=member.size
            count+=1
            if total>100*1024*1024 or count>10000:
                raise ValueError("Archive exceeds safe limits")
            target=destination.joinpath(*parts[1:])
            if member.isdir():
                target.mkdir(parents=True,exist_ok=True)
            else:
                if len(parts)<2:
                    raise ValueError("Invalid archive root file")
                target.parent.mkdir(parents=True,exist_ok=True)
                if target.exists():
                    raise ValueError("Duplicate archive file: "+member.name)
                payload=source.extractfile(member)
                if payload is None:
                    raise ValueError("Missing archive member data")
                with payload, target.open("xb") as output:
                    shutil.copyfileobj(payload,output)
                target.chmod(0o755 if member.mode & 0o111 else 0o644)
    # Directories created under root's umask can become 0700.
    # Normalize each extracted directory so the service can traverse src/legacy.
    for directory in [destination,*destination.rglob("*")]:
        if directory.is_dir():
            directory.chmod(0o755)
    if not (destination/"deploy"/"install-homelab.py").is_file() or not (
            destination/"src"/"legacy"/"anime-discovery-live.py").is_file():
        raise ValueError("Archive is not an Anime Discovery release")


def upgrade_archive(root,archive,*,db_path,service="anime-discovery.service",runner=command,
                    verbose=False,log=None,readiness_attempts=15,sleep=time.sleep,backup=False):
    report=log if log is not None else (lambda message: None)
    def progress(message):
        if verbose:
            report("[upgrade] "+message)
    progress("Validating archive installation and database")
    root=Path(root).absolute()
    archive=Path(archive).absolute()
    if not root.is_dir() or root.is_symlink() or (root/".git").exists():
        raise ValueError("Archive upgrades require an installed archive directory")
    if not db_path:
        raise ValueError("Database path required")
    db_path=Path(db_path)
    if db_path.is_symlink() or not db_path.is_file():
        raise ValueError("Configured database must be a regular file")
    with sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",uri=True) as db:
        version=db.execute("SELECT version FROM schema_version").fetchone()
        if not version or version[0]!=1:
            raise ValueError("Unsupported database version")
    temp=Path(tempfile.mkdtemp(prefix=".anime-discovery-staging-",dir=root.parent))
    staged=temp/"anime-discovery"
    staged.mkdir()
    timestamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    old=root.with_name(root.name+".before-"+timestamp)
    db_backup=Path(str(db_path)+".before-archive-"+timestamp+".bak")
    if old.exists() or (backup and db_backup.exists()):
        shutil.rmtree(temp)
        raise FileExistsError("Versioned upgrade backup already exists")
    stopped=False
    swapped=False
    try:
        progress("Extracting release archive into staging directory")
        _extract(archive,staged)
        # The staged root is created with mkdir's default mode, not the
        # installed directory's mode. Preserve its actual accessibility before
        # activating it: a service account must be able to chdir into it.
        old_stat=root.stat()
        os.chmod(staged,stat.S_IMODE(old_stat.st_mode))
        progress("Preserved application root directory permissions")
        # Preserve service-user ownership if the installed tree is user-owned.
        if os.geteuid()==0 and old_stat.st_uid!=0:
            for path in [staged,*staged.rglob("*")]:
                os.chown(path,old_stat.st_uid,old_stat.st_gid)
        if backup:
            progress("Backing up SQLite database (explicit --backup)")
            with sqlite3.connect(db_path.resolve().as_uri()+"?mode=ro",uri=True) as src:
                with sqlite3.connect(db_backup) as dest:
                    src.backup(dest)
                    if dest.execute("PRAGMA integrity_check").fetchone()[0]!="ok":
                        raise ValueError("Database backup integrity failure")
            db_backup.chmod(0o600)
        else:
            progress("No database backup requested; schema unchanged")
        progress("Stopping "+service)
        runner("systemctl","stop",service)
        stopped=True
        progress("Activating staged release; keeping previous code backup")
        root.rename(old)
        try:
            staged.rename(root)
            swapped=True
        except BaseException:
            old.rename(root)
            raise
        progress("Starting "+service)
        runner("systemctl","start",service)
        progress("Waiting for service readiness")
        if type(readiness_attempts) is not int or readiness_attempts<1:
            raise ValueError("Invalid readiness_attempts")
        for attempt in range(readiness_attempts):
            try:
                runner("systemctl","is-active","--quiet",service)
                progress("Service active; upgrade completed")
                break
            except Exception:
                if attempt==readiness_attempts-1:
                    raise RuntimeError("Service not active after "+str(readiness_attempts)+" readiness checks") from None
                progress("Service not yet active (check "+str(attempt+1)+"/"+str(readiness_attempts)+")")
                sleep(1)
        if not backup:
            shutil.rmtree(old)
            progress("Removed temporary rollback code after successful startup")
        return {"updated":True,"backup_code":str(old) if backup else None,
                "backup_database":str(db_backup) if backup else None,
                "source_archive":str(archive)}
    except BaseException:
        progress("Upgrade failed; restoring original application code and service")
        if swapped:
            # Roll back code without leaving failed code trees by default.
            failed=root.with_name(root.name+".failed-"+timestamp)
            root.rename(failed)
            old.rename(root)
            if not backup:
                shutil.rmtree(failed,ignore_errors=True)
        if stopped:
            try:
                runner("systemctl","start",service)
            except Exception:
                pass
        raise
    finally:
        shutil.rmtree(temp,ignore_errors=True)
