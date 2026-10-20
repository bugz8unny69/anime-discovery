"""Deterministic parsing of configured anime names and release episode numbers."""
import re


def resolve_release(release_name, series_map):
    """Return confirmed identifiers from an exact configured alias plus episode.

    Does not infer identities from fuzzy title similarity or contact a provider.
    Supports S01E02 and '[Group] Show - 02' naming.
    """
    if not isinstance(release_name,str) or not isinstance(series_map,dict):
        return None
    title = re.sub(r"^\[[^\]]{1,80}\]\s*", "", release_name.strip())
    matches = []
    for alias, identity in series_map.items():
        if not isinstance(alias,str) or not alias.strip() or not isinstance(identity,dict):
            continue
        pattern = re.escape(alias.strip())
        pattern = re.sub(r"(?:\\\ |\\\.|\\_|\\-)+", r"[ ._-]+", pattern)
        prefix = r"^" + pattern
        season_episode = re.match(prefix + r"[ ._-]+S(?P<s>\d{1,2})E(?P<e>\d{1,4})(?!\d)",title,re.I)
        dash_episode = re.match(prefix + r"\s+-\s+(?P<e>\d{1,4})(?:v\d+)?(?!\d)",title,re.I)
        if not season_episode and not dash_episode:
            continue
        season = int(season_episode.group("s")) if season_episode else identity.get("season",1)
        episode = int((season_episode or dash_episode).group("e"))
        if type(season) is not int or season<1 or episode<1:
            continue
        matches.append({"tvdb_id":identity.get("tvdb_id"),
                        "anidb_id":identity.get("anidb_id"),
                        "season":season,"episode":episode})
    if len(matches)!=1:
        return None
    return matches[0]
