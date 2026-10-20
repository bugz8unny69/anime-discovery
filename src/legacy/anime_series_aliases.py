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

def remember_verified_season(db, config_dir, series_id, season):
    """Populate Recognized Names from server-side verified provenance only.

    Never trust IDs or alias text in the browser POST. The user supplies only
    a DB series id and season; an exact proven memory record supplies all IDs.
    Multiple seasons get distinct qualified keys, not a stale AniDB alias.
    """
    from anime_verified_season_memory import for_series
    try:
        sid,season=int(series_id),int(season)
    except (TypeError,ValueError):
        raise ValueError("Valid series and season required") from None
    if sid<=0 or season<=0:
        raise ValueError("Valid series and season required")
    matching=[row for row in for_series(db,sid) if row["season"]==season]
    if len(matching)!=1:
        raise ValueError("No independently verified season identity available")
    row=matching[0]
    key=row["title"]+" [S%02d]"%season
    old=load_config(config_dir)["settings"]["identity"]["series_map"].get(key)
    required={"tvdb_id":int(row["tvdb_id"]),
              "anidb_id":int(row["anidb_id"]),"season":season,
              "verify_each_episode":True}
    if old is not None:
        if (str(old.get("tvdb_id"))!=str(required["tvdb_id"])
                or str(old.get("anidb_id"))!=str(required["anidb_id"])
                or old.get("season",1)!=season
                or old.get("verify_each_episode") is not True):
            raise ValueError("Conflicting Recognized Names mapping; no overwrite")
        return {"series_id":sid,"season":season,"alias":key,"already_exists":True}
    settings=load_config(config_dir)["settings"]
    mappings=dict(settings["identity"]["series_map"])
    for candidate in mappings:
        if candidate.casefold()==key.casefold():
            raise ValueError("Conflicting case-insensitive Recognized Names alias")
    mappings[key]=required
    set_setting(config_dir,"identity.series_map",mappings)
    return {"alias":key,**required,"series_id":sid,"already_exists":False}
