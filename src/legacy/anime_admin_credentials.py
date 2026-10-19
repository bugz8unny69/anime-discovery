"""Safely update fresh-build dashboard and webhook credentials without resetting state."""
import fcntl
import getpass
import json
import os
import stat
import tempfile
from pathlib import Path

def configure_credentials(directory, *, prompt=getpass.getpass):
    directory=Path(directory)
    path=directory/"secrets.json"
    if path.is_symlink() or not path.is_file():
        raise ValueError("Existing secrets.json regular file required")
    webhook=prompt("Autobrr webhook token (leave blank to keep existing): ")
    admin=prompt("Dashboard admin password (leave blank to keep existing): ")
    lock=directory/".settings.lock"
    with lock.open("a+b") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        data=json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data,dict):
            raise ValueError("secrets.json must be a JSON object")
        if webhook:
            data["web_token"]=webhook
        if admin:
            data["admin_password"]=admin
        if not data.get("web_token") or not data.get("admin_password"):
            raise ValueError("Both webhook token and admin password are required")
        if data["web_token"]==data["admin_password"]:
            raise ValueError("Admin password must differ from webhook token")
        meta=path.stat()
        fd,tmp=tempfile.mkstemp(prefix=".secrets-",dir=directory)
        try:
            with os.fdopen(fd,"w",encoding="utf-8") as output:
                json.dump(data,output,indent=2,sort_keys=True)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
            os.chmod(tmp,0o600)
            if os.geteuid()==0:
                os.chown(tmp,meta.st_uid,meta.st_gid)
            os.replace(tmp,path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
        fcntl.flock(handle,fcntl.LOCK_UN)
    return {"credentials_updated":True,"restart_required":True}
