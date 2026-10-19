"""Interactively configure Jellyfin refresh for an existing fresh-build install."""
import fcntl
import getpass
import json
import os
import tempfile
from pathlib import Path
from anime_flat_config import load_config, validate_config
from anime_admin_settings import set_setting

def configure_jellyfin(directory, *, ask=input, secret_prompt=getpass.getpass):
    directory=Path(directory)
    current=load_config(directory)
    url=ask("Jellyfin base URL (http/https): ").strip()
    key=secret_prompt("Jellyfin API key (blank to keep existing): ")
    settings=current["settings"]
    secrets=dict(current["secrets"])
    if key:
        secrets["jellyfin_api_key"]=key
    # Validate all fields before modifying any file.
    settings["jellyfin"].update(enabled=True,base_url=url)
    validate_config(settings,secrets)
    path=directory/"secrets.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Expected regular secrets.json")
    lock=directory/".settings.lock"
    with lock.open("a+b") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        # Re-read under the lock, preserving unrelated secret updates.
        saved=json.loads(path.read_text(encoding="utf-8"))
        if key:
            saved["jellyfin_api_key"]=key
        if not saved.get("jellyfin_api_key"):
            raise ValueError("Jellyfin API key missing")
        info=path.stat()
        fd,tmp=tempfile.mkstemp(prefix=".jellyfin-secrets-",dir=directory)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as stream:
                json.dump(saved,stream,indent=2,sort_keys=True)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(tmp,0o600)
            if os.geteuid()==0:
                os.chown(tmp,info.st_uid,info.st_gid)
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        fcntl.flock(handle,fcntl.LOCK_UN)
    set_setting(directory,"jellyfin.base_url",url)
    set_setting(directory,"jellyfin.enabled",True)
    return {"jellyfin_scan_enabled":True,"restart_required":True}
