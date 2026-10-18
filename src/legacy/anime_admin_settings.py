"""Atomic settings.json editor for anime-discovery-admin.

Never stores configuration in SQLite. Secrets are not echoed or edited here.
"""
import json
import os
import tempfile
from pathlib import Path

from anime_flat_config import DEFAULT_SETTINGS, load_config


def set_setting(directory, dotted_key, value):
    directory=Path(directory)
    parts=dotted_key.split(".")
    if len(parts)!=2 or parts[0] not in DEFAULT_SETTINGS or parts[1] not in DEFAULT_SETTINGS[parts[0]]:
        raise ValueError("Unknown setting: "+dotted_key)
    path=directory/"settings.json"
    current=load_config(directory)
    settings={section:dict(values) for section,values in current["settings"].items()}
    settings[parts[0]][parts[1]]=value
    # Validate without changing global loader functions or publishing bad JSON.
    from anime_flat_config import validate_config
    validated=validate_config(settings,current["secrets"])
    if validated["settings"][parts[0]][parts[1]]!=value:
        raise ValueError("Setting validation failed")
    fd,tmp=tempfile.mkstemp(prefix=".settings-",suffix=".json",dir=directory)
    try:
        with os.fdopen(fd,"w",encoding="utf-8") as f:
            json.dump(settings,f,indent=2,sort_keys=True)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.chmod(tmp,path.stat().st_mode & 0o777)
        os.replace(tmp,path)
        dfd=os.open(directory,os.O_RDONLY)
        try: os.fsync(dfd)
        finally: os.close(dfd)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
    return validated["settings"][parts[0]][parts[1]]
