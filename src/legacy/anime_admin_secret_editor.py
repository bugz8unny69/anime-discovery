"""Interactive supported-secret editor. Does not accept password values in command arguments."""
import getpass
from anime_flat_config import ALLOWED_SECRET_KEYS

def prompt_secret(key, prompt=getpass.getpass):
    if key not in ALLOWED_SECRET_KEYS:
        raise ValueError("Unsupported credential")
    return prompt(key+" (blank keeps existing): ")

def set_secret(directory, key, *, clear=False, prompt=getpass.getpass, confirm=input):
    """Change one secret, or explicitly clear one. Blank input means keep."""
    import fcntl
    import os
    from pathlib import Path
    from anime_flat_config import load_config, validate_config
    from anime_admin_integrations import _write
    if key not in ALLOWED_SECRET_KEYS:
        raise ValueError("Unsupported credential")
    directory=Path(directory)
    with (directory/".settings.lock").open("a+b") as handle:
        fcntl.flock(handle,fcntl.LOCK_EX)
        if os.geteuid()==0:
            info=(directory/"settings.json").stat()
            os.fchown(handle.fileno(),info.st_uid,info.st_gid)
            os.fchmod(handle.fileno(),0o600)
        current=load_config(directory)
        data=dict(current["secrets"])
        if clear:
            if key=="admin_password":
                raise ValueError("Rotate the administrator password instead of clearing it")
            if confirm("Type CLEAR to remove "+key+": ")!="CLEAR":
                return {"secret":key,"changed":False}
            data.pop(key,None)
        else:
            value=prompt_secret(key,prompt)
            if not value:
                return {"secret":key,"changed":False}
            if key=="admin_password":
                from anime_dashboard_auth import set_password
                if value==data.get("web_token"):
                    raise ValueError("Admin password and webhook token must differ")
                set_password(value)
                data.pop("admin_password",None)
            else:
                data[key]=value
        validate_config(current["settings"],data)
        changed=data!=current["secrets"]
        if changed:
            _write(directory/"secrets.json",data,0o600)
        return {"secret":key,"changed":changed or key=="admin_password",
                "status":"Set" if data.get(key) or key=="admin_password" else "Not set",
                "restart_required":changed and key!="admin_password"}
