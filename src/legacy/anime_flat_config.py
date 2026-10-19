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
    "identity": {"reuse_verified_cache": True, "series_map": {}},
    "qbittorrent": {"priority_mode": "normal", "manage_download_limit": False, "base_url": "http://127.0.0.1:8080", "username": "", "cleanup_source": True},
    "prowlarr": {"enabled": False, "base_url": ""},
    "jellyfin": {"write_trial_nfo": True, "enabled": False, "base_url": ""},
    "shoko": {"enabled": False, "base_url": "", "auto_link_verified": False,
              "poll_seconds": 60}
}
ALLOWED_SECRET_KEYS = {"shoko_api_key", "qbittorrent_password", "jellyfin_api_key", "web_token", "admin_password", "prowlarr_api_key"}

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
    for section, key in (("identity","reuse_verified_cache"),("jellyfin","write_trial_nfo"),("jellyfin","enabled"),
                         ("shoko","enabled"),("shoko","auto_link_verified")):
        if type(result[section][key]) is not bool:
            raise ValueError("Invalid boolean setting: "+section+"."+key)
    series_map = result["identity"]["series_map"]
    if not isinstance(series_map,dict) or len(series_map)>500:
        raise ValueError("identity.series_map must be a mapping with at most 500 aliases")
    seen = set()
    for alias, mapping in series_map.items():
        if not isinstance(alias,str) or not alias.strip() or len(alias)>200:
            raise ValueError("Invalid series alias")
        if alias.strip().casefold() in seen:
            raise ValueError("Duplicate series alias")
        seen.add(alias.strip().casefold())
        if not isinstance(mapping,dict) or set(mapping)-{"tvdb_id","anidb_id","season"}:
            raise ValueError("Invalid mapping for "+alias)
        for key in ("tvdb_id","anidb_id"):
            value = mapping.get(key)
            if type(value) not in (str,int) or not str(value).isdigit() or int(value)<=0:
                raise ValueError("Invalid "+key+" for "+alias)
        season = mapping.get("season",1)
        if type(season) is not int or season<=0:
            raise ValueError("Invalid season for "+alias)
    jellyfin=result["jellyfin"]
    if not isinstance(jellyfin["base_url"],str):
        raise ValueError("Invalid Jellyfin URL")
    if jellyfin["enabled"]:
        if not jellyfin["base_url"].startswith(("http://","https://")):
            raise ValueError("Enabled Jellyfin scan requires its URL")
        if not secrets.get("jellyfin_api_key"):
            raise ValueError("Enabled Jellyfin scan requires jellyfin_api_key in secrets.json")
    if type(result["prowlarr"]["enabled"]) is not bool:
        raise ValueError("Invalid prowlarr.enabled")
    if not isinstance(result["prowlarr"]["base_url"],str):
        raise ValueError("Invalid prowlarr.base_url")
    if result["prowlarr"]["enabled"] and not result["prowlarr"]["base_url"].startswith(("http://","https://")):
        raise ValueError("Enabled Prowlarr requires a configured URL")
    if result["prowlarr"]["enabled"] and not secrets.get("prowlarr_api_key"):
        raise ValueError("Enabled Prowlarr requires prowlarr_api_key in secrets.json")
    if not isinstance(result["shoko"]["base_url"],str):
        raise ValueError("Invalid Shoko URL")
    if type(result["shoko"]["poll_seconds"]) is not int or result["shoko"]["poll_seconds"]<10:
        raise ValueError("Invalid Shoko polling interval")
    if "admin_password" in secrets and secrets.get("admin_password")==secrets.get("web_token"):
        raise ValueError("Dashboard admin password must differ from webhook token")
    if set(secrets)-ALLOWED_SECRET_KEYS:
        raise ValueError("Unknown secrets keys")
    if any(not isinstance(v,str) for v in secrets.values()):
        raise ValueError("Secret values must be strings")
    if secrets and directory is not None:
        mode=(Path(directory)/"secrets.json").stat().st_mode & 0o777
        if mode & 0o077:
            raise PermissionError("secrets.json must not be accessible by group/others")
    return {"settings":result,"secrets":secrets}
