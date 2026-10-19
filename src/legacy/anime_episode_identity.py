"""Conservative TVDB season/episode to AniDB episode resolver.

No implicit numbering equivalence: mappings must be explicitly vetted for a
specific TVDB series and particular episode. Anime/series AniDB IDs are distinct.
"""
def resolve_exact_episode(settings,*,tvdb_id,season,episode):
    if any(type(v) is not int or v<=0 for v in (tvdb_id,episode)) or type(season) is not int or season<0:
        raise ValueError("Invalid TVDB episode key")
    mappings=settings.get("identity",{}).get("episode_map",{})
    entry=mappings.get(f"{tvdb_id}:{season}:{episode}")
    if not isinstance(entry,dict) or entry.get("verified") is not True:
        return None
    aid=entry.get("anidb_episode_id")
    if type(aid) is not int or aid<=0:
        return None
    return aid
