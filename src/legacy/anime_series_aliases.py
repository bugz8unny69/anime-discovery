"""Manage trusted title aliases in settings.json rather than SQLite."""
from anime_admin_settings import set_setting
from anime_flat_config import load_config


def add_alias(config_dir, alias, tvdb_id, anidb_id, season=1):
    if not isinstance(alias,str) or not alias.strip():
        raise ValueError("Series alias is required")
    alias = alias.strip()
    tvdb_id, anidb_id, season = int(tvdb_id), int(anidb_id), int(season)
    if min(tvdb_id,anidb_id,season)<=0:
        raise ValueError("IDs and season must be positive")
    settings = load_config(config_dir)["settings"]
    mappings = dict(settings["identity"]["series_map"])
    for existing in mappings:
        if existing.casefold() == alias.casefold() and existing != alias:
            raise ValueError("A case-insensitive alias already exists")
    mappings[alias] = {"tvdb_id":tvdb_id,"anidb_id":anidb_id,"season":season}
    set_setting(config_dir,"identity.series_map",mappings)
    return {"alias":alias,"tvdb_id":tvdb_id,"anidb_id":anidb_id,"season":season}


def remove_alias(config_dir, alias):
    mappings=dict(load_config(config_dir)["settings"]["identity"]["series_map"])
    if alias not in mappings:
        raise ValueError("Alias not found")
    del mappings[alias]
    set_setting(config_dir,"identity.series_map",mappings)
    return {"alias":alias,"removed":True}
