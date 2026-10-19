"""Interactive integration configuration, preserving unrelated settings and secrets."""
import fcntl
import getpass
import json
import os
import tempfile
from pathlib import Path
from anime_flat_config import load_config, validate_config

SERVICES={
    "sonarr":(("base_url",str),("root_folder",str),("quality_profile_id",int)),
    "ntfy":(("server",str),("topic",str),("dashboard_url",str),("reminder_hours",int)),
    "tvdb":(("base_url",str),),
    "shoko":(("base_url",str),("poll_seconds",int)),
}
SECRET_NAMES={"sonarr":"sonarr_api_key","ntfy":"ntfy_token",
              "tvdb":"tvdb_api_key","shoko":"shoko_api_key"}

def _write(path, value, mode):
    if path.is_symlink() or not path.is_file():
        raise ValueError("Refusing unsafe configuration file")
    info=path.stat()
    fd,tmp=tempfile.mkstemp(prefix=".integration-",suffix=".json",dir=path.parent)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as out:
            json.dump(value,out,indent=2,sort_keys=True)
            out.write("\n")
            out.flush()
            os.fsync(out.fileno())
        os.chmod(tmp,mode)
        if os.geteuid()==0:
            os.chown(tmp,info.st_uid,info.st_gid)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)

def configure(directory, service, *, ask=input, secret_prompt=getpass.getpass):
    if service not in SERVICES:
        raise ValueError("Unsupported integration")
    directory=Path(directory)
    settings_path=directory/"settings.json"
    secrets_path=directory/"secrets.json"
    lock=directory/".settings.lock"
    changes={}
    for field,kind in SERVICES[service]:
        raw=ask(service+"."+field+" (blank to preserve): ").strip()
        if raw:
            try:
                changes[field]=kind(raw)
            except ValueError:
                raise ValueError("Invalid integration field "+field) from None
    key=SECRET_NAMES[service]
    secret=secret_prompt(service+" API token (blank to preserve): ").strip()
    enabled_answer=ask("Enable "+service+" now? [yes/no/keep]: ").strip().lower()
    if enabled_answer not in ("yes","no","keep"):
        raise ValueError("Select yes, no or keep")
    with lock.open("a+b") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        try:
            if os.geteuid()==0:
                owner=settings_path.stat()
                os.fchown(handle.fileno(),owner.st_uid,owner.st_gid)
                os.fchmod(handle.fileno(),0o600)
            current=load_config(directory)
            settings={k:dict(v) for k,v in current["settings"].items()}
            secrets=dict(current["secrets"])
            settings[service].update(changes)
            if enabled_answer!="keep":
                settings[service]["enabled"]=enabled_answer=="yes"
            if service=="shoko":
                # Shoko linking remains fail-closed until a reviewed API contract is approved.
                settings[service]["auto_link_verified"]=False
            if secret:
                secrets[key]=secret
            validate_config(settings,secrets)
            if secret:
                _write(secrets_path,secrets,0o600)
            _write(settings_path,settings,settings_path.stat().st_mode & 0o777)
            return {"integration":service,"enabled":settings[service]["enabled"],
                    "restart_required":True,"secrets_preserved":not bool(secret)}
        finally:
            fcntl.flock(handle,fcntl.LOCK_UN)
