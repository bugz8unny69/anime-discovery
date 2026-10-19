"""Flat-file configuration for the Anime Discovery daemon.

settings.json contains non-secret preferences; secrets.json contains credentials.
Neither is stored in the operational SQLite database. No secret values are logged.
"""
import json
import os
from pathlib import Path

DEFAULT_CONFIG_DIR = Path("/etc/anime-discovery")
DEFAULT_SETTINGS = {
    "daemon": {"concurrency": 4, "lease_seconds": 300, "database_path": "/var/lib/anime-discovery/anime-discovery.db"},
    "web": {"host": "0.0.0.0", "port": 8765},
    "storage": {"download_root": "", "trial_root": ""},
    "identity": {"reuse_verified_cache": True},
    "qbittorrent": {"priority_mode": "normal", "manage_download_limit": False, "base_url": "http://127.0.0.1:8080", "username": "", "cleanup_source": True},
    "jellyfin": {"write_trial_nfo": True},
    "shoko": {"enabled": False, "base_url": "", "auto_link_verified": False,
              "poll_seconds": 60}
}
ALLOWED_SECRET_KEYS = {"shoko_api_key", "qbittorrent_password", "jellyfin_api_key", "web_token"}

def _read_object(path):
    path=Path(path)
    if not path.is_file():
        raise FileNotFoundError(path)
    with path.open("r",encoding="utf-8") as f:
        obj=json.load(f)
    if not isinstance(obj,dict):
        raise ValueError(f"{path.name} must contain a JSON object")
    return obj

def load_config(directory=DEFAULT_CONFIG_DIR):
    directory=Path(directory)
    settings=_read_object(directory/"settings.json")
    secrets=_read_object(directory/"secrets.json")
    return validate_config(settings,secrets,directory=directory)

def validate_config(settings,secrets,*,directory=None):
    unknown=set(settings)-set(DEFAULT_SETTINGS)
    if unknown:
        raise ValueError("Unknown settings sections: "+", ".join(sorted(unknown)))
    result={}
    for section, defaults in DEFAULT_SETTINGS.items():
        value=settings.get(section,{})
        if not isinstance(value,dict) or set(value)-set(defaults):
            raise ValueError("Invalid keys in "+section)
        result[section]={**defaults,**value}
    if not isinstance(result["daemon"]["concurrency"],int) or not 1<=result["daemon"]["concurrency"]<=32:
        raise ValueError("daemon.concurrency must be 1..32")
    if not isinstance(result["daemon"]["lease_seconds"],int) or result["daemon"]["lease_seconds"]<30:
        raise ValueError("Invalid daemon lease_seconds")
    if not isinstance(result["daemon"]["database_path"],str) or not result["daemon"]["database_path"]:
        raise ValueError("Invalid database path")
    if not isinstance(result["web"]["host"],str) or not result["web"]["host"] or type(result["web"]["port"]) is not int or not 1<=result["web"]["port"]<=65535:
        raise ValueError("Invalid web listener")
    if any(not isinstance(result["storage"][key],str) for key in ("download_root","trial_root")):
        raise ValueError("Invalid storage paths")
    if not isinstance(result["qbittorrent"]["base_url"],str) or not isinstance(result["qbittorrent"]["username"],str):
        raise ValueError("Invalid qBittorrent connection")
    if type(result["qbittorrent"]["cleanup_source"]) is not bool:
        raise ValueError("Invalid cleanup_source")
    if result["qbittorrent"]["priority_mode"]!="normal":
        raise ValueError("Unsupported torrent priority mode")
    if result["qbittorrent"]["manage_download_limit"] is not False:
        raise ValueError("qBittorrent owns its download limit")
    for section, key in (("identity","reuse_verified_cache"),("jellyfin","write_trial_nfo"),
                         ("shoko","enabled"),("shoko","auto_link_verified")):
        if type(result[section][key]) is not bool:
            raise ValueError("Invalid boolean setting: "+section+"."+key)
    if not isinstance(result["shoko"]["base_url"],str):
        raise ValueError("Invalid Shoko URL")
    if type(result["shoko"]["poll_seconds"]) is not int or result["shoko"]["poll_seconds"]<10:
        raise ValueError("Invalid Shoko polling interval")
    if set(secrets)-ALLOWED_SECRET_KEYS:
        raise ValueError("Unknown secrets keys")
    if any(not isinstance(v,str) for v in secrets.values()):
        raise ValueError("Secret values must be strings")
    if secrets and directory is not None:
        mode=(Path(directory)/"secrets.json").stat().st_mode & 0o777
        if mode & 0o077:
            raise PermissionError("secrets.json must not be accessible by group/others")
    return {"settings":result,"secrets":secrets}
