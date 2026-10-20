"""Fail-closed planning for a fixed E01-E06 sample within one confirmed season.

This module does not add, start, stop, delete, or download torrents. Callers
must hold a verified series/season identity, inspect a complete qBittorrent
file manifest, and apply the plan while their NEW torrent is stopped.
"""
import re
from pathlib import PurePosixPath

VIDEO_SUFFIXES = frozenset({".mkv", ".mp4", ".m4v", ".avi"})
_SEASON_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,4})(?!\d)", re.I)
_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])(?:Episode|EP|E)[ ._-]*(?P<episode>\d{1,4})(?!\d)", re.I)
_DASH_EPISODE = re.compile(r"\s-\s(?P<episode>\d{1,4})(?!\d)")
_SEASON_FOLDER = re.compile(r"^(?:Season[ ._-]*|S)(?P<season>\d{1,2})$", re.I)
_EXTRA_E = re.compile(r"(?<![A-Za-z])E\d{1,4}(?!\d)", re.I)
_X_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])(?P<season>\d{1,2})x(?P<episode>\d{1,4})(?!\d)", re.I)
_BRACKET_EPISODE = re.compile(r"[\[(](?P<episode>\d{1,4})[\])]")
_JP_EPISODE = re.compile(r"第\s*(?P<episode>\d{1,4})\s*話")
_BARE_EPISODE = re.compile(r"^\s*(?P<episode>\d{1,4})\s*$")
_SEASON_TOKEN = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})(?![A-Za-z0-9])", re.I)
_MORE_EPISODES = re.compile(
    r"^\s*(?:[-+~&]|to)\s*(?:E(?:P(?:isode)?)?[ ._-]*)?\d{1,4}(?![A-Za-z0-9])", re.I)



_RELEASE_EPISODE = re.compile(
    r"(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<episode>\d{1,4})(?!\d)", re.I)
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
    """Return a defensible (season, episode), never guess file ordering."""
    if not isinstance(name, str) or not name or len(name) > 2048 or "\\" in name:
        raise SelectionNeedsReview("Invalid qBittorrent file name")
    relative = PurePosixPath(name)
    if (relative.is_absolute() or any(p in (".", "..", "") for p in name.split("/"))
            or not relative.name):
        raise SelectionNeedsReview("Unsafe qBittorrent file path")
    if relative.suffix.lower() not in VIDEO_SUFFIXES:
        return None

    base = relative.stem
    explicit = list(_SEASON_EPISODE.finditer(base))
    x_form = list(_X_EPISODE.finditer(base))
    # A multi-episode video (E01E02, 01-02, 01+02, etc.) cannot be
    # represented as one E01 file; never stage a partial mapping.
    if len(explicit) + len(x_form) > 1 or len(_EXTRA_E.findall(base)) > 1:
        raise SelectionNeedsReview("Multi-episode video requires review: " + name)

    folder_seasons = [int(match.group("season"))
                      for part in relative.parts[:-1]
                      if (match := _SEASON_FOLDER.fullmatch(part))]
    season_tokens = [int(m.group("season")) for m in _SEASON_TOKEN.finditer(base)]
    season_hints = set(folder_seasons + season_tokens)
    if len(season_hints) > 1 or (season_hints and confirmed_season not in season_hints):
        raise SelectionNeedsReview("Conflicting season hints: " + name)

    if explicit or x_form:
        match = (explicit or x_form)[0]
        season = int(match.group("season"))
        episode = int(match.group("episode"))
        if _MORE_EPISODES.match(base[match.end():]):
            raise SelectionNeedsReview("Multi-episode video requires review: " + name)
    else:
        # Common fan-sub naming conventions. A bracketed [01] is meaningful,
        # whereas [1080p] and [2026] are not episode indicators. Bare "01"
        # is trusted only inside an explicit verified season directory.
        matches = []
        for pattern in (_EPISODE, _DASH_EPISODE,
                        _BRACKET_EPISODE, _JP_EPISODE):
            matches.extend(pattern.finditer(base))
        if not matches and folder_seasons:
            matches = list(_BARE_EPISODE.finditer(base))
        numbers = {int(m.group("episode")) for m in matches}
        # Four-digit bracket groups may be release years rather than episodes.
        # Requiring explicit provider mapping later is safer than guessing.
        if any(m.re is _BRACKET_EPISODE and
               1900 <= int(m.group("episode")) <= 2100 for m in matches):
            raise SelectionNeedsReview("Ambiguous four-digit year/episode: " + name)
        if len(numbers) != 1 or not matches:
            raise SelectionNeedsReview("Episode number missing or ambiguous: " + name)
        for match in matches:
            if _MORE_EPISODES.match(base[match.end():]):
                raise SelectionNeedsReview("Multi-episode video requires review: " + name)
        season = confirmed_season
        episode = numbers.pop()

    if season < 1 or episode < 1 or season != confirmed_season:
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


def plan_gated_first_six(files, *, season, probe_verified=False, already_satisfied=()):
    """Return a two-phase E01-first plan; no torrent or storage mutation.

    Phase 1 fetches ONLY E01, withholding E02-E06 until the worker has
    durably recorded that this exact E01 file passed actual ffprobe
    Japanese+English validation. Phase 2 returns all still-needed E01-E06.
    'probe_verified' must come from independently verified durable evidence,
    never a release name, torrent status or a caller-controlled webhook.
    """
    if type(probe_verified) is not bool:
        raise ValueError("probe_verified must be boolean")
    # Validate all file paths and per-episode uniqueness before choosing
    # either phase. Don't silently omit ambiguous E07+ files.
    plan = plan_first_six(files, season=season, already_satisfied=already_satisfied)
    if 1 not in plan["wanted_episodes"] and 1 not in plan["already_satisfied"]:
        raise SelectionNeedsReview("E01 not available or previously verified; cannot authorize batch probe")
    if not probe_verified:
        if 1 in plan["already_satisfied"]:
            # A separately verified E01 still requires the caller to explicitly
            # attest durable probe verification before unlocking other files.
            wanted = {}
        else:
            wanted = {1: plan["wanted_episodes"][1]}
        phase = "PROBE_E01"
    else:
        wanted = plan["wanted_episodes"]
        phase = "UNLOCK_E02_E06"
    included = set(wanted.values())
    all_indices = set(plan["wanted_indices"]) | set(plan["skip_indices"])
    return {
        "phase": phase,
        "season": season,
        "wanted_episodes": wanted,
        "wanted_indices": sorted(included),
        "skip_indices": sorted(all_indices - included),
        "already_satisfied": plan["already_satisfied"],
        "out_of_window_episodes": plan["out_of_window_episodes"],
        "file_names_by_index": plan["file_names_by_index"],
    }


def plan_verified_trial(files, *, season, start_episode, episode_map,
                        probe_verified=False):
    """Six episodes from an independently verified release-to-TVDB map.

    The *caller* must obtain 'episode_map' from a trusted provider mapping,
    not calculate an offset from file ordering, lowest episode number or
    release metadata. Every video in the pack must have an explicit mapping.
    Supports season-relative S02E01, absolute S02E13->S02E01,
    Part 2 filenames 01->canonical E13, and continuous E1001.
    """
    if type(season) is not int or not 1 <= season <= 100:
        raise ValueError("Verified positive season required")
    if type(start_episode) is not int or not 1 <= start_episode <= 9994:
        raise ValueError("Verified trial start required")
    if type(probe_verified) is not bool:
        raise ValueError("Probe attestation must be boolean")
    if (not isinstance(episode_map, dict) or not episode_map or
            any(type(src) is not int or src < 1 or src > 9999 or
                type(dst) is not int or dst < 1 or dst > 9999
                for src,dst in episode_map.items()) or
            len(set(episode_map.values())) != len(episode_map)):
        raise ValueError("Explicit, unique verified episode map required")
    if not isinstance(files, list) or not files:
        raise SelectionNeedsReview("Torrent file inventory unavailable")
    mapped, names, canonical_used = {}, {}, set()
    for entry in files:
        if not isinstance(entry, dict):
            raise SelectionNeedsReview("Invalid torrent file entry")
        index, name = entry.get("index"), entry.get("name")
        if type(index) is not int or index < 0 or index in names:
            raise SelectionNeedsReview("Duplicate or invalid torrent file index")
        parsed = _video_episode(name, season)
        names[index] = name
        if parsed is None:
            continue
        release_episode = parsed[1]
        if release_episode not in episode_map:
            raise SelectionNeedsReview("Video episode lacks verified mapping")
        canonical = episode_map[release_episode]
        if canonical in canonical_used:
            raise SelectionNeedsReview("Duplicate canonical episode in torrent")
        canonical_used.add(canonical)
        mapped[canonical] = index
    if start_episode not in mapped:
        raise SelectionNeedsReview("First trial episode not found in verified manifest")
    end_episode=start_episode+5
    wanted = {ep:idx for ep,idx in mapped.items()
              if start_episode <= ep <= end_episode and
                 (probe_verified or ep == start_episode)}
    wanted_indices = sorted(wanted.values())
    skipped_indices = sorted(set(names) - set(wanted_indices))
    return {
        "phase": "UNLOCK_REMAINING" if probe_verified else "PROBE_FIRST_EPISODE",
        "season": season, "start_episode": start_episode,
        "end_episode": end_episode,
        "wanted_episodes": dict(sorted(wanted.items())),
        "wanted_indices": wanted_indices, "skip_indices": skipped_indices,
        "out_of_window_episodes": sorted(ep for ep in mapped
                                         if not start_episode <= ep <= end_episode),
        "file_names_by_index": dict(sorted(names.items())),
    }
