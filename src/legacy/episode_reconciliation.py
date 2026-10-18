"""Offline, fail-closed episode-number reconciliation. No network/DB writes.

Inputs MUST be assembled by privileged adapters, not copied from RSS or torrent
payloads. An approved identity binding is a prerequisite, not established here.
The returned candidate is NOT an authorization to download or approve mapping.
"""
import re
from collections.abc import Mapping

class ReconciliationError(ValueError):
    pass

_SPECIAL = re.compile(r'(?<![A-Za-z0-9])(?:OVA|OAV|ONA|SPECIALS?|SP|RECAP|MOVIE|NCOP|NCED|PV|TRAILER)(?![A-Za-z0-9])', re.I)
_RANGE = re.compile(r'(?<!\d)\d{1,3}\s*(?:-|~|&|\+|,)\s*(?:E(?:P)?\s*)?\d{1,3}(?!\d)', re.I)
_EXPLICIT = re.compile(r'(?<![A-Za-z0-9])S(?P<season>\d{1,2})\s*E(?P<ep>\d{1,3})(?!\d)', re.I)
_ORDINARY = re.compile(r'(?<![A-Za-z0-9])(?:Episode\s*|EP\.?\s*|E\s*|-\s+)(?P<ep>\d{1,3})(?=$|[\s\[\(\.]|v\d+\b)', re.I)
_SEASON = re.compile(r'(?<![A-Za-z0-9])(?:Season\s*\d+|S\d{1,2})(?![A-Za-z0-9])', re.I)

def parse_release_number(title):
    """Parse exactly one release number, including absolute values > 6."""
    if not isinstance(title, str) or not title.strip():
        raise ReconciliationError('EMPTY_RELEASE')
    if _SPECIAL.search(title):
        raise ReconciliationError('SPECIAL_RELEASE')
    if _SEASON.search(title) and not _EXPLICIT.search(title):
        raise ReconciliationError('UNSUPPORTED_SEASON_MARKER')
    if _RANGE.search(title):
        raise ReconciliationError('MULTI_EPISODE_RELEASE')
    explicit = list(_EXPLICIT.finditer(title))
    rest = _EXPLICIT.sub(' ', title)
    ordinary = list(_ORDINARY.finditer(rest))
    if len(explicit) + len(ordinary) != 1:
        raise ReconciliationError('AMBIGUOUS_RELEASE_NUMBER')
    if explicit:
        m = explicit[0]
        season = int(m.group('season'))
        episode = int(m.group('ep'))
        if _SEASON.search(rest):
            raise ReconciliationError('CONFLICTING_SEASON')
        mode = 'season_episode'
    else:
        m = ordinary[0]
        episode = int(m.group('ep'))
        season = None
        if _SEASON.search(rest):
            raise ReconciliationError('UNSUPPORTED_SEASON_MARKER')
        mode = 'number_only'
    if not 1 <= episode <= 999 or (season is not None and not 1 <= season <= 99):
        raise ReconciliationError('INVALID_NUMBER')
    return {'release_episode': episode, 'release_season': season, 'numbering': mode}

def _positive_int(value):
    return type(value) is int and value > 0

def reconcile(*, release_title, series_id, anilist_id, binding, episode_evidence):
    """Require two independent, trusted adapter snapshots to agree exactly.

    binding: controller-side verified binding {series_id, provider, provider_id,
             state, binding_id}; supplied only by privileged storage lookup.
    episode_evidence: two independent trusted records (e.g. Sonarr and AniDB),
             each with {provider, series_id, anilist_id, entries}.
    entries are exact [{release_season: int|None, release_episode: int,
                        canonical_season: int, canonical_episode: int,
                        kind: 'REGULAR'}]. No inferred offsets or gaps.
    """
    parsed = parse_release_number(release_title)
    if not _positive_int(series_id) or not _positive_int(anilist_id):
        raise ReconciliationError('INVALID_SERIES_ID')
    if not isinstance(binding, Mapping) or (binding.get('series_id') != series_id or
        binding.get('provider') != 'anilist' or binding.get('provider_id') != anilist_id or
        binding.get('state') != 'ACTIVE' or not _positive_int(binding.get('binding_id'))):
        raise ReconciliationError('IDENTITY_NOT_BOUND')
    if not isinstance(episode_evidence, (list, tuple)) or len(episode_evidence) != 2:
        raise ReconciliationError('TWO_SOURCES_REQUIRED')
    providers = set()
    mapped = []
    for record in episode_evidence:
        if not isinstance(record, Mapping):
            raise ReconciliationError('INVALID_EVIDENCE')
        provider = record.get('provider')
        if provider not in ('sonarr', 'anidb') or provider in providers:
            raise ReconciliationError('INDEPENDENT_SOURCES_REQUIRED')
        providers.add(provider)
        if record.get('series_id') != series_id or record.get('anilist_id') != anilist_id:
            raise ReconciliationError('EVIDENCE_IDENTITY_MISMATCH')
        entries = record.get('entries')
        if not isinstance(entries, list) or not entries:
            raise ReconciliationError('MISSING_EPISODE_EVIDENCE')
        matches = []
        seen_keys = set()
        seen_canonical = set()
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise ReconciliationError('INVALID_EPISODE_ENTRY')
            rs, re_num = entry.get('release_season'), entry.get('release_episode')
            cs, ce = entry.get('canonical_season'), entry.get('canonical_episode')
            if (rs is not None and not _positive_int(rs)) or not _positive_int(re_num) or not _positive_int(cs) or not _positive_int(ce):
                raise ReconciliationError('INVALID_EPISODE_ENTRY')
            key = (rs, re_num)
            canonical = (cs, ce)
            if key in seen_keys or canonical in seen_canonical:
                raise ReconciliationError('CONFLICTING_EPISODE_ENTRIES')
            seen_keys.add(key)
            seen_canonical.add(canonical)
            if key == (parsed['release_season'], parsed['release_episode']):
                if entry.get('kind') != 'REGULAR':
                    raise ReconciliationError('NON_REGULAR_EPISODE')
                matches.append(canonical)
        if len(matches) != 1:
            raise ReconciliationError('MAPPING_NOT_FOUND')
        mapped.append(matches[0])
    if mapped[0] != mapped[1]:
        raise ReconciliationError('SOURCE_MAPPING_CONFLICT')
    if mapped[0][0] != 1 or not 1 <= mapped[0][1] <= 6:
        raise ReconciliationError('OUTSIDE_TRIAL_WINDOW')
    return {'status': 'CANDIDATE_ONLY', 'canonical_mapping_authorized': False,
            'series_id': series_id, 'anilist_id': anilist_id,
            'binding_id': binding['binding_id'], **parsed,
            'canonical_season': mapped[0][0], 'canonical_episode': mapped[0][1],
            'sources': sorted(providers)}
