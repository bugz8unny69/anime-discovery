"""One registry for setting defaults and dashboard field presentation.

New ordinary settings go in SCHEMA once. The configuration loader derives
DEFAULT_SETTINGS here, and the dashboard renders scalar fields marked visible.
Cross-field constraints and secret handling remain server-side.
"""
from copy import deepcopy


def field(default, *, label=None, visible=True, minimum=None, maximum=None,
          choices=None, help_text=None):
    kind = ("boolean" if type(default) is bool else
            "integer" if type(default) is int else
            "string" if isinstance(default,str) else "object")
    if kind=="object" and visible:
        raise ValueError("Complex settings require a dedicated editor")
    if choices is not None and (kind!="string" or default not in choices):
        raise ValueError("Invalid schema choices")
    return {"default":default,"type":kind,"label":label,
            "visible":bool(visible),"min":minimum,"max":maximum,
            "choices":choices,"help":help_text}


# A section becomes a standard dashboard form when dashboard=True. Secrets
# are referenced by key only; their values are never part of this registry.
SCHEMA = {
    "daemon": {"dashboard":False,"fields":{
        "concurrency":field(4,visible=False,minimum=1,maximum=32),
        "lease_seconds":field(300,visible=False,minimum=30),
        "database_path":field("/var/lib/anime-discovery/anime-discovery.db",visible=False)}},
    "web": {"dashboard":False,"fields":{
        "host":field("0.0.0.0",visible=False),
        "port":field(8765,visible=False,minimum=1,maximum=65535)}},
    "storage": {"dashboard":False,"fields":{
        "download_root":field("",visible=False),
        "trial_root":field("",visible=False)}},
    "identity": {"dashboard":True,"title":"Identity matching","fields":{
        "reuse_verified_cache":field(True,visible=False),
        "series_map":field({},visible=False),
        "episode_map":field({},visible=False),
        "match_threshold_pct":field(90,label="Minimum title match score (%)",
            minimum=50,maximum=100,help_text="Title similarity never bypasses episode verification.")}},
    "qbittorrent": {"dashboard":False,"fields":{
        "priority_mode":field("normal",visible=False),
        "manage_download_limit":field(False,visible=False),
        "base_url":field("http://127.0.0.1:8080",visible=False),
        "username":field("",visible=False),
        "cleanup_source":field(True,visible=False)}},
    "prowlarr": {"dashboard":True,"title":"Prowlarr","credential":"prowlarr_api_key","fields":{
        "enabled":field(False),
        "base_url":field("",label="Base URL")}},
    "jellyfin": {"dashboard":True,"title":"Jellyfin","credential":"jellyfin_api_key",
                "test_connection":True,"fields":{
        "write_trial_nfo":field(True,visible=False),
        "enabled":field(False),
        "base_url":field("",label="Base URL")}},
    "sonarr": {"dashboard":True,"title":"Sonarr","credential":"sonarr_api_key",
               "test_connection":True,"fields":{
        "enabled":field(False),
        "base_url":field("",label="Base URL"),
        "root_folder":field("",label="Root folder"),
        "quality_profile_id":field(0,label="Quality profile ID",minimum=0),
        "quality_profile_name":field("Anime",label="Quality profile name")}},
    "ntfy": {"dashboard":True,"title":"NTFY","credential":"ntfy_token",
             "credential_label":"Access Token","test_connection":True,"fields":{
        "enabled":field(False),
        "server":field(""),
        "topic":field(""),
        "reminder_hours":field(24,minimum=1),
        "dashboard_url":field("",label="Dashboard URL")}},
    "tvdb": {"dashboard":True,"title":"TVDB","credential":"tvdb_api_key",
             "test_connection":True,"fields":{
        "enabled":field(False),
        "base_url":field("https://api4.thetvdb.com/v4",label="Base URL")}},
    "anidb": {"dashboard":True,"title":"AniDB",
              "description":"Public title catalog: no API key required. An HTTP API client name and version are required for exact episode IDs; no UDP API key or account password is used. Saving does not send a request to AniDB.",
              "fields":{
        "enabled":field(True),
        "http_api_url":field("",visible=False),
        "client":field("",label="HTTP API Client Name",
                       help_text="Enter the exact client name registered with AniDB."),
        "clientver":field(1,label="Client Version",minimum=1,maximum=999999)}},
    "shoko": {"dashboard":True,"title":"Shoko","credential":"shoko_api_key",
              "test_connection":True,"fields":{
        "enabled":field(False),
        "base_url":field("",label="Base URL"),
        "auto_link_verified":field(False,label="Auto Link Verified"),
        "poll_seconds":field(60,minimum=10),
        "import_folder_id":field(0,label="Import folder ID",minimum=0)}}
}


def defaults():
    """Fresh defaults: avoid shared mutable dictionaries across validation runs."""
    return {section:{key:deepcopy(spec["default"]) for key,spec in cfg["fields"].items()}
            for section,cfg in SCHEMA.items()}


def dashboard_sections():
    return {name:cfg for name,cfg in SCHEMA.items() if cfg.get("dashboard")}
