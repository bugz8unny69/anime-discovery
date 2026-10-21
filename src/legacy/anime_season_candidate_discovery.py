"""Read-only discovery of season-compatible AniDB records from Anime-Lists.

A mapped AniDB ID is a candidate, not independent proof of an anime title or
the internal AniDB episode ID. Never authorize acquisition from this helper.
"""
import xml.etree.ElementTree as ET
from anime_identity_mapping_v4 import resolve_episode
from anime_identification_probe import load_anidb

def season_candidates(mapping_xml,catalog,tvdb_id,season,episode,*,limit=20):
    if mapping_xml is None or catalog is None or type(season) is not int or season<1:
        return []
    if type(episode) is not int or episode<1:
        return []
    root=ET.fromstring(mapping_xml)
    if root.tag!="anime-list":
        raise ValueError("Invalid Anime-Lists cross-reference root")
    ids=set()
    for item in root.findall("anime"):
        if item.get("tvdbid")==str(tvdb_id) and item.get("anidbid","").isdecimal():
            ids.add(item.get("anidbid"))
    # Resolve each candidate independently; keep only unique explicit/default
    # episode mappings that agree with the *release* season.
    mapped={}
    for aid in sorted(ids):
        rule=resolve_episode(mapping_xml,aid,str(tvdb_id),episode)
        if rule is not None and rule["tvdb_season"]==season:
            mapped[aid]=rule
    if not mapped:
        return []
    titles={}
    for aid,names in load_anidb(catalog):
        if aid in mapped:
            titles[aid]=[n[:180] for n in names[:12]]
            if len(titles)==len(mapped):
                break
    return [{"anidb_id":aid,"tvdb_id":str(tvdb_id),
             "titles":titles.get(aid,[]),"title_index_present":aid in titles,
             "episode_rule":mapped[aid]}
            for aid in sorted(mapped)[:limit]]
