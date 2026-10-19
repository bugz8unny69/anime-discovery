"""Non-destructive migration for existing settings.json and secrets.json.

The migration fills missing supported settings from defaults and NEVER
overwrites existing values, secret keys, paths, or credentials. Unknown
legacy settings are reported, not discarded or silently rewritten.
"""
import copy
import fcntl
import json
import os
import stat
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from anime_flat_config import DEFAULT_SETTINGS, ALLOWED_SECRET_KEYS, validate_config


def _read(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected an existing regular file: "+str(path))
    with path.open(encoding="utf-8") as stream:
        obj=json.load(stream)
    if not isinstance(obj,dict):
        raise ValueError(path.name+" must contain a JSON object")
    return obj


def _plan(directory):
    directory=Path(directory)
    settings=_read(directory/"settings.json")
    secrets=_read(directory/"secrets.json")
    missing=[]
    unknown=[]
    merged=copy.deepcopy(settings)
    for name,defaults in DEFAULT_SETTINGS.items():
        if name not in merged:
            merged[name]=copy.deepcopy(defaults)
            missing.extend(name+"."+key for key in defaults)
        elif not isinstance(merged[name],dict):
            raise ValueError("Existing section is not a JSON object: "+name)
        else:
            for key,value in defaults.items():
                if key not in merged[name]:
                    merged[name][key]=copy.deepcopy(value)
                    missing.append(name+"."+key)
            unknown.extend(name+"."+key for key in merged[name] if key not in defaults)
    unknown.extend(name for name in merged if name not in DEFAULT_SETTINGS)
    secret_unknown=sorted(set(secrets)-ALLOWED_SECRET_KEYS)
    # Never include values from either file in the report.
    return merged,secrets,sorted(missing),sorted(unknown),secret_unknown


def migrate(directory, *, apply=False):
    directory=Path(directory)
    if not directory.is_dir() or directory.is_symlink():
        raise ValueError("Expected existing configuration directory")
    lock_path=directory/".settings.lock"
    with lock_path.open("a+b") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        try:
            return _migrate_locked(directory,apply=apply)
        finally:
            fcntl.flock(lock,fcntl.LOCK_UN)


def _migrate_locked(directory,*,apply):
    path=directory/"settings.json"
    secret_path=directory/"secrets.json"
    settings,secrets,missing,unknown,unknown_secrets=_plan(directory)
    report={"mode":"apply" if apply else "preview",
            "missing_settings":missing,"unknown_settings":unknown,
            "unknown_secret_keys":unknown_secrets,
            "secrets_modified":False,"backup":None,
            "changed":False}
    if unknown or unknown_secrets:
        report["ready"]=False
        report["reason"]="Unknown legacy keys require manual review; no values were discarded"
        if apply:
            raise ValueError(report["reason"]+": "+", ".join(unknown+unknown_secrets))
        return report
    # Validation checks final types and catches incompatible legacy values.
    # The secrets file is read as-is and never changed or printed.
    validate_config(settings,secrets,directory=directory)
    report["ready"]=True
    if not apply or not missing:
        return report
    meta=path.stat()
    if not stat.S_ISREG(meta.st_mode):
        raise ValueError("settings.json must be a regular file")
    # Back up the exact original bytes without replacing the original.
    timestamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup=directory/("settings.json.before-migrate-"+timestamp+".bak")
    fd,tmp=tempfile.mkstemp(prefix=".settings-migrate-",suffix=".json",dir=directory)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as stream:
            json.dump(settings,stream,indent=2,sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(tmp,stat.S_IMODE(meta.st_mode))
        os.chown(tmp,meta.st_uid,meta.st_gid)
        # Exclusive-create the backup and keep its original owner and mode.
        with path.open("rb") as original, backup.open("xb") as output:
            os.fchmod(output.fileno(),stat.S_IMODE(meta.st_mode))
            os.fchown(output.fileno(),meta.st_uid,meta.st_gid)
            while chunk:=original.read(1024*1024):
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        # Refuse to touch secrets; ensure it was not replaced during migration.
        if secret_path.is_symlink() or not secret_path.is_file():
            raise ValueError("secrets.json changed during migration")
        os.replace(tmp,path)
        fd_dir=os.open(directory,os.O_RDONLY)
        try:os.fsync(fd_dir)
        finally:os.close(fd_dir)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    report["backup"]=str(backup)
    report["changed"]=True
    return report
