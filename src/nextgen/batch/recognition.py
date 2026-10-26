"""Advisory release scope hints; never evidence for acquiring an episode.

The webhook title is untrusted. Only canonical provider mappings and a
hash-verified per-file torrent inventory may authorize a later selection.
"""
from dataclasses import dataclass
import re

_SEASON_EP = re.compile(r'(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,4})(?![A-Za-z0-9])', re.I)
_SEASON = re.compile(r'(?<![A-Za-z0-9])S(?P<season>\d{1,2})(?![A-Za-z0-9])|\bSeason[ ._-]*S?(?P<word>\d{1,2})\b', re.I)
_PACK = re.compile(r'\b(?:Batch|Complete[ ._-]*Season|Season[ ._-]*Pack|Complete)\b', re.I)
_SPECIAL = re.compile(r'\b(?:OVA|OAV|ONA|Specials?|NCOP|NCED|PV|Trailer|Recap|Movie|Extras?)\b', re.I)
_RANGE = re.compile(r'(?<!\d)\d{1,4}\s*(?:-|~|&|\+|,|to)\s*(?:E(?:P)?\s*)?\d{1,4}(?!\d)', re.I)
_REPEAT = re.compile(r'(?<![A-Za-z])E\d{1,4}[ ._-]*E\d{1,4}(?!\d)', re.I)


@dataclass(frozen=True)
class ReleaseScope:
    kind: str
    season_hint: int | None = None
    episode_hint: int | None = None


def release_scope_hint(release_name):
    """Classify titles for routing/diagnostics only; no episode assertions."""
    unknown = ReleaseScope('unknown')
    if type(release_name) is not str or not 1 <= len(release_name) <= 2048:
        return unknown
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in release_name):
        return unknown
    episodes = list(_SEASON_EP.finditer(release_name))
    seasons = {int(m.group('season') or m.group('word')) for m in _SEASON.finditer(release_name)}
    seasons.update(int(m.group('season')) for m in episodes)
    if len(seasons) > 1 or len(episodes) > 1 or _RANGE.search(release_name) or _REPEAT.search(release_name):
        return ReleaseScope('ambiguous')
    season = next(iter(seasons), None)
    special = bool(_SPECIAL.search(release_name))
    if season == 0:
        return ReleaseScope('special', 0, int(episodes[0].group('episode')) if episodes else None)
    if episodes:
        number = int(episodes[0].group('episode'))
        if number < 1 or special or _PACK.search(release_name):
            return ReleaseScope('ambiguous', season)
        return ReleaseScope('single_episode', season, number)
    if season is not None or _PACK.search(release_name):
        return ReleaseScope('mixed_pack' if special else 'season_pack', season)
    if special:
        return ReleaseScope('special')
    return unknown
