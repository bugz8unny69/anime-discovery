"""Reuse the existing Anime-Lists resolver for explicit episode-number maps.

This does not assume that a release's labels equal AniDB episode numbers.
A trusted upstream identity worker must independently establish that fact
before passing these numbers. This module performs no network or qB writes.
"""
import hashlib

from anime_identity_mapping_v4 import resolve_episode


def from_anime_lists(xml_bytes, *, anidb_id, tvdb_id, season, release_episodes):
    """Resolve each confirmed AniDB episode number to one TVDB season episode.

    Returns a source-bound mapping and evidence fingerprint. Never derives
    mappings merely by sorting torrent files, subtracting season lengths, or
    interpreting a date. Ambiguous provider rules fail closed.
    """
    if not isinstance(xml_bytes, bytes) or not 0 < len(xml_bytes) <= 16 * 1024 * 1024:
        raise ValueError("Validated Anime-Lists XML bytes required")
    if (not str(anidb_id).isdigit() or int(anidb_id) <= 0 or
            not str(tvdb_id).isdigit() or int(tvdb_id) <= 0 or
            type(season) is not int or not 1 <= season <= 100):
        raise ValueError("Verified AniDB / TVDB series pair and season required")
    if not isinstance(release_episodes, (list, tuple, set)) or not release_episodes:
        raise ValueError("Release episode numbers required")
    nums = list(release_episodes)
    if (len(nums) > 240 or len(nums) != len(set(nums))
            or any(type(n) is not int or not 1 <= n <= 9999 for n in nums)):
        raise ValueError("Invalid or duplicate episode numbers")
    mapping = {}
    used = set()
    for number in sorted(nums):
        found = resolve_episode(xml_bytes, int(anidb_id), int(tvdb_id), number)
        if (not found or found.get("tvdb_season") != season or
                type(found.get("tvdb_episode")) is not int):
            raise ValueError("AniDB-to-TVDB episode mapping absent or conflicting")
        canonical=found["tvdb_episode"]
        if canonical in used:
            raise ValueError("Multiple AniDB episodes map to one TVDB episode")
        used.add(canonical)
        mapping[number]=canonical
    return {"episode_map": mapping,
            "evidence_ref":"anime-lists:"+hashlib.sha256(xml_bytes).hexdigest()[:32],
            "source":"Anime-Lists"}
