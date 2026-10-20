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
        # The Recognized Names editor now saves season-qualified aliases
        # as "Show [S02]" so two AniDB productions can coexist under one
        # TVDB series. The suffix is an identity *scope*, not a literal part
        # of release filenames.
        qualified=re.fullmatch(r"(.+?)\\s+\\[S(\\d{2})\\]",alias.strip(),re.I)
        base=qualified.group(1) if qualified else alias.strip()
        configured_season=identity.get("season",1)
        if (type(configured_season) is not int or configured_season<1 or
                (qualified and int(qualified.group(2))!=configured_season)):
            continue
        pattern = re.escape(base)
        pattern = re.sub(r"(?:\\\\\\ |\\\\\\.|\\\\_|\\\\-)+", r"[ ._-]+", pattern)
        prefix = r"^" + pattern
        season_episode = re.match(prefix + r"[ ._-]+S(?P<s>\\d{1,2})E(?P<e>\\d{1,4})(?!\\d)",title,re.I)
        dash_episode = re.match(prefix + r"\\s+-\\s+(?P<e>\\d{1,4})(?:v\\d+)?(?!\\d)",title,re.I)
        if not season_episode and not dash_episode:
            continue
        season = int(season_episode.group("s")) if season_episode else configured_season
        episode = int((season_episode or dash_episode).group("e"))
        if season != configured_season or episode<1:
            # Critical: S02 may be a different AniDB production from S01.
            # Never send the old AniDB ID with a new season's episode number.
            continue
        matches.append({"tvdb_id":identity.get("tvdb_id"),
                        "anidb_id":identity.get("anidb_id"),
                        "season":season,"episode":episode})
    if len(matches)!=1:
        return None
    return matches[0]
