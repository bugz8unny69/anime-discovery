"""Shared settings service for CLI and web API, no subprocess calls."""
import fcntl
import json
import os
import tempfile
from pathlib import Path
from anime_flat_config import DEFAULT_SETTINGS, ALLOWED_SECRET_KEYS, load_config, validate_config
from anime_settings_schema import auto_applied_field

def snapshot(directory):
    current=load_config(directory)
    from anime_dashboard_auth import read
    return {"settings":current["settings"],
            "credential_status":{key:bool(current["secrets"].get(key) or
                (key=="admin_password" and read())) for key in sorted(ALLOWED_SECRET_KEYS)},
            "source":"persisted",
            "apply_mode":"automatically reloads dashboard settings"}

def apply_settings(directory,changes):
    """Atomic single-file persistence, no implicit daemon restart or reload."""
    if not isinstance(changes,dict) or not changes:
        raise ValueError("Supply settings changes")
    directory=Path(directory)
    with (directory/".settings.lock").open("a+b") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        if os.geteuid()==0:
            metadata=(directory/"settings.json").stat()
            os.fchown(lock.fileno(),metadata.st_uid,metadata.st_gid)
            os.fchmod(lock.fileno(),0o600)
        current=load_config(directory)
        result={section:dict(values) for section,values in current["settings"].items()}
        touched=[]
        for section,fields in changes.items():
            if section not in DEFAULT_SETTINGS or not isinstance(fields,dict):
                raise ValueError("Unknown settings section")
            for field,value in fields.items():
                if field not in DEFAULT_SETTINGS[section]:
                    raise ValueError("Unsupported setting "+section+"."+field)
                if result[section][field]!=value:
                    result[section][field]=value
                    touched.append(section+"."+field)
        validate_config(result,current["secrets"])
        if not touched:
            return {"saved":False,"changed":[],"restart_required":False,
                    "runtime_applied":False}
        path=directory/"settings.json"
        if path.is_symlink() or not path.is_file():
            raise ValueError("Refusing nonregular settings file")
        metadata=path.stat()
        fd,tmp=tempfile.mkstemp(prefix=".settings-",dir=directory)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as handle:
                json.dump(result,handle,indent=2,sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.chmod(tmp,metadata.st_mode & 0o777)
            if os.geteuid()==0:
                os.chown(tmp,metadata.st_uid,metadata.st_gid)
            os.replace(tmp,path)
            parent=os.open(directory,os.O_RDONLY)
            try:os.fsync(parent)
            finally:os.close(parent)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        restart_required=any(not auto_applied_field(*name.split(".",1)) for name in touched)
        return {"saved":True,"changed":sorted(touched),"restart_required":restart_required,
                "apply_mode":"restart_required" if restart_required else "automatic",
                "runtime_applied":False}
