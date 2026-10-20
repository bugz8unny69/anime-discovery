"""Fail-closed planning for a fixed E01-E06 sample within one confirmed season.

This module does not add, start, stop, delete, or download torrents. Callers
must hold a verified series/season identity, inspect a complete qBittorrent
file manifest, and apply the plan while their NEW torrent is stopped.
"""
import re
from pathlib import PurePosixPath

VIDEO_SUFFIXES = frozenset({".mkv", ".mp4", ".m4v", ".avi"})
_SEASON_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,3})(?!\d)", re.I)
_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])(?:Episode|EP|E)[ ._-]*(?P<episode>\d{1,3})(?!\d)", re.I)
_DASH_EPISODE = re.compile(r"\s-\s(?P<episode>\d{1,3})(?!\d)")
_SEASON_FOLDER = re.compile(r"^Season[ ._-]*(?P<season>\d{1,2})$", re.I)
_EXTRA_E = re.compile(r"(?<![A-Za-z])E\d{1,3}(?!\d)", re.I)



_RELEASE_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,3})(?!\d)", re.I)
_RELEASE_SEASON = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})(?![A-Za-z0-9])", re.I)
_RELEASE_SEASON_WORD = re.compile(
    r"\bSeason[ ._-]*S?(?P<season>\d{1,2})\b", re.I)
_BATCH_WORD = re.compile(r"\b(?:Batch|Complete[ ._-]*Season|Season[ ._-]*Pack)\b", re.I)


def release_scope_hint(release_name):
    """Advisory release classification, never authorization or canonical ID.

    Useful for a safe Needs Review explanation. Even a visible "Season S2"
    cannot prove per-file season/episode mappings or TVDB/AniDB identity.
    """
    if not isinstance(release_name, str) or not release_name.strip():
        return {"kind": "unknown", "season_hint": None, "episode_hint": None}
    episodes = list(_RELEASE_EPISODE.finditer(release_name))
    if any(int(match.group("season")) == 0 for match in episodes):
        match = next(x for x in episodes if int(x.group("season")) == 0)
        return {"kind": "special", "season_hint": 0,
                "episode_hint": int(match.group("episode"))}
    season_words = [int(x.group("season"))
                    for x in _RELEASE_SEASON_WORD.finditer(release_name)]
    season_tokens = [int(x.group("season"))
                     for x in _RELEASE_SEASON.finditer(release_name)]
    all_seasons = set(season_words + season_tokens
                      + [int(x.group("season")) for x in episodes])
    is_pack = bool(_BATCH_WORD.search(release_name) or season_words)
    if len(all_seasons) > 1:
        return {"kind": "ambiguous_season", "season_hint": None,
                "episode_hint": None}
    if is_pack:
        return {"kind": "season_pack", "season_hint":
                next(iter(all_seasons)) if all_seasons else None,
                "episode_hint": None}
    if len(episodes) == 1:
        match = episodes[0]
        return {"kind": "single_episode",
                "season_hint": int(match.group("season")),
                "episode_hint": int(match.group("episode"))}
    return {"kind": "unknown", "season_hint": None, "episode_hint": None}

class SelectionNeedsReview(ValueError):
    """A torrent cannot safely be mapped to one season and unique episodes."""


def _video_episode(name, confirmed_season):
    """Return (season, episode), or None for non-video file entries."""
    if not isinstance(name, str) or not name or len(name) > 2048 or "\\" in name:
        raise SelectionNeedsReview("Invalid qBittorrent file name")
    relative = PurePosixPath(name)
    if (relative.is_absolute() or any(p in (".", "..") for p in name.split("/"))
            or not relative.name):
        raise SelectionNeedsReview("Unsafe qBittorrent file path")
    if relative.suffix.lower() not in VIDEO_SUFFIXES:
        return None

    base = relative.stem
    explicit = list(_SEASON_EPISODE.finditer(base))
    # One video file may not silently represent multiple episodes.
    if len(explicit) > 1 or len(_EXTRA_E.findall(base)) > 1:
        raise SelectionNeedsReview("Multi-episode video requires review: " + name)

    folder_seasons = [int(match.group("season"))
                      for part in relative.parts[:-1]
                      if (match := _SEASON_FOLDER.fullmatch(part))]
    if len(set(folder_seasons)) > 1:
        raise SelectionNeedsReview("Conflicting season folders: " + name)
    folder_season = folder_seasons[0] if folder_seasons else None

    if explicit:
        season = int(explicit[0].group("season"))
        episode = int(explicit[0].group("episode"))
    else:
        identified = list(_EPISODE.finditer(base))
        if not identified:
            identified = list(_DASH_EPISODE.finditer(base))
        if len(identified) != 1:
            raise SelectionNeedsReview("Episode number missing or ambiguous: " + name)
        season = folder_season or confirmed_season
        episode = int(identified[0].group("episode"))

    if (season < 1 or episode < 1 or
            season != confirmed_season or
            (folder_season is not None and folder_season != season)):
        raise SelectionNeedsReview("Season/episode mismatch: " + name)
    return season, episode


def plan_first_six(files, *, season, already_satisfied=()):
    """Build a conservative selection from a complete qBittorrent manifest.

    The caller must supply a *confirmed* season and already-verified episodes.
    Only unique E01-E06 files not already satisfied are wanted. All other
    files receive priority zero, including E07+, extras, and duplicate-safe
    already-satisfied files. Mixed seasons, unknown episodes and duplicates
    require operator review; never apply a partial plan in those cases.
    """
    if type(season) is not int or not 1 <= season <= 100:
        raise ValueError("Confirmed positive season required")
    if not isinstance(files, list) or not files:
        raise SelectionNeedsReview("Torrent file inventory unavailable")
    try:
        satisfied = set(already_satisfied)
    except TypeError:
        raise ValueError("Invalid satisfied episode collection") from None
    if any(type(ep) is not int or not 1 <= ep <= 6 for ep in satisfied):
        raise ValueError("Satisfied episodes must be verified E01-E06")

    names = {}
    episodes = {}
    video_count = 0
    for entry in files:
        if not isinstance(entry, dict):
            raise SelectionNeedsReview("Invalid torrent file entry")
        index, name = entry.get("index"), entry.get("name")
        if type(index) is not int or index < 0 or index in names:
            raise SelectionNeedsReview("Missing or duplicate qBittorrent file index")
        parsed = _video_episode(name, season)
        names[index] = name
        if parsed is None:
            continue
        video_count += 1
        _, episode = parsed
        if episode in episodes:
            raise SelectionNeedsReview("Multiple videos mapped to episode E%02d" % episode)
        episodes[episode] = index

    if not video_count:
        raise SelectionNeedsReview("Torrent has no identifiable video files")
    wanted = {ep: index for ep, index in episodes.items()
              if ep <= 6 and ep not in satisfied}
    wanted_indices = sorted(wanted.values())
    skip_indices = sorted(set(names) - set(wanted_indices))
    return {
        "season": season,
        "wanted_episodes": dict(sorted(wanted.items())),
        "wanted_indices": wanted_indices,
        "skip_indices": skip_indices,
        "already_satisfied": sorted(satisfied & episodes.keys()),
        "out_of_window_episodes": sorted(ep for ep in episodes if ep > 6),
        "file_names_by_index": dict(sorted(names.items())),
    }
