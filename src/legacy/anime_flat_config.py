"""Flat-file configuration for the Anime Discovery daemon.

settings.json contains non-secret preferences; secrets.json contains credentials.
Neither is stored in the operational SQLite database. No secret values are logged.
"""
import json
import os
from pathlib import Path

DEFAULT_CONFIG_DIR = Path("/etc/anime-discovery")
from anime_settings_schema import defaults, validate_scalar_fields

DEFAULT_SETTINGS = defaults()
ALLOWED_SECRET_KEYS = {"shoko_api_key", "sonarr_api_key", "ntfy_token", "tvdb_api_key", "qbittorrent_password", "jellyfin_api_key", "web_token", "admin_password", "prowlarr_api_key"}

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
    validate_scalar_fields(result)
    from anime_staging_permissions import parse_mode
    parse_mode(result["storage"]["staged_directory_mode"],directory=True)
    parse_mode(result["storage"]["staged_file_mode"],directory=False)
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
                         ("shoko","enabled"),("shoko","auto_link_verified"),("anidb","enabled")):
        if type(result[section][key]) is not bool:
            raise ValueError("Invalid boolean setting: "+section+"."+key)
    threshold=result["identity"]["match_threshold_pct"]
    if type(threshold) is not int or not 50<=threshold<=100:
        raise ValueError("identity.match_threshold_pct must be an integer from 50 to 100")
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
    episode_map=result["identity"]["episode_map"]
    if not isinstance(episode_map,dict) or len(episode_map)>5000:
        raise ValueError("identity.episode_map must be a mapping of at most 5000 entries")
    import re
    for key,item in episode_map.items():
        if not isinstance(key,str) or not re.fullmatch(r"[1-9][0-9]*:[0-9]+:[1-9][0-9]*",key):
            raise ValueError("Invalid TVDB episode identity key")
        if not isinstance(item,dict) or set(item)!={"anidb_episode_id","verified"} or type(item["anidb_episode_id"]) is not int or item["anidb_episode_id"]<=0 or item["verified"] is not True:
            raise ValueError("Exact AniDB episode mapping requires verified=true")
    anidb=result["anidb"]
    if (not isinstance(anidb["http_api_url"],str) or
            not isinstance(anidb["client"],str) or
            type(anidb["clientver"]) is not int or anidb["clientver"]<1):
        raise ValueError("Invalid AniDB HTTP configuration")
    # Backward-compatible setting: the only accepted explicit URL is AniDB's
    # official endpoint. An empty URL also selects that endpoint.
    if anidb["http_api_url"] not in ("", "http://api.anidb.net:9001/httpapi"):
        raise ValueError("Use the official AniDB HTTP API endpoint; no gateway needed")
    if anidb["client"] and not __import__("re").fullmatch(r"[A-Za-z0-9_-]{3,32}",anidb["client"]):
        raise ValueError("AniDB HTTP client identifier invalid")
    if anidb["clientver"]>999999:
        raise ValueError("AniDB HTTP client version invalid")
    sonarr=result["sonarr"]
    if type(sonarr["enabled"]) is not bool or not isinstance(sonarr["base_url"],str) or not isinstance(sonarr["root_folder"],str) or type(sonarr["quality_profile_id"]) is not int or not isinstance(sonarr["quality_profile_name"],str):
        raise ValueError("Invalid Sonarr settings")
    if sonarr["enabled"] and (not sonarr["base_url"].startswith(("http://","https://")) or not sonarr["root_folder"].startswith("/") or (sonarr["quality_profile_id"]<=0 and not sonarr["quality_profile_name"].strip()) or not secrets.get("sonarr_api_key")):
        raise ValueError("Enabled Sonarr requires URL, API key, root folder and quality profile")
    ntfy=result["ntfy"]
    if type(ntfy["enabled"]) is not bool or type(ntfy["reminder_hours"]) is not int or ntfy["reminder_hours"]<1 or any(not isinstance(ntfy[k],str) for k in ("server","topic","dashboard_url")):
        raise ValueError("Invalid NTFY settings")
    if ntfy["enabled"] and (not ntfy["server"].startswith("https://") or not ntfy["topic"] or not ntfy["dashboard_url"].startswith("https://")):
        raise ValueError("Enabled NTFY requires HTTPS server, topic and dashboard URL")
    tvdb=result["tvdb"]
    if type(tvdb["enabled"]) is not bool or not isinstance(tvdb["base_url"],str) or (tvdb["enabled"] and (not tvdb["base_url"].startswith("https://") or not secrets.get("tvdb_api_key"))):
        raise ValueError("Invalid TVDB settings")
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
    if result["shoko"]["enabled"] and (not result["shoko"]["base_url"].startswith(("http://","https://")) or not secrets.get("shoko_api_key")):
        raise ValueError("Enabled Shoko requires a base URL and API key")
    if result["shoko"]["auto_link_verified"] and not result["shoko"]["enabled"]:
        raise ValueError("Shoko auto-link requires enabled Shoko")
    if type(result["shoko"]["import_folder_id"]) is not int or result["shoko"]["import_folder_id"]<0:
        raise ValueError("Invalid Shoko import folder ID")
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
