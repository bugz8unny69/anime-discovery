"""Read-only authenticated-source boundary; no episode mapping authorization.

Only instantiate from privileged controller configuration. Never accept URL, key,
expected ID, or transport from RSS/torrent/discovery request fields.
"""
import hashlib
import ipaddress
import json
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone

from anilist_adapter import lookup_by_id, MetadataLookupError

class SourceError(ValueError):
    pass


def _positive(value):
    return type(value) is int and value > 0


def _decode(raw):
    if not isinstance(raw, bytes) or len(raw) > 2_000_000:
        raise SourceError('INVALID_RESPONSE_SIZE')
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise SourceError('INVALID_JSON') from exc


def _read(request, transport):
    try:
        if transport is not None:
            return _decode(transport(request))
        with urllib.request.urlopen(request, timeout=12) as response:
            return _decode(response.read(2_000_001))
    except SourceError:
        raise
    except Exception as exc:
        raise SourceError('SOURCE_UNAVAILABLE') from exc


def _sonarr_base(base):
    if not isinstance(base, str):
        raise SourceError('INVALID_BASE_URL')
    u = urllib.parse.urlsplit(base)
    if u.username or u.password or u.query or u.fragment or u.path.rstrip('/'):
        raise SourceError('INVALID_BASE_URL')
    if u.scheme not in ('https', 'http') or not u.hostname:
        raise SourceError('INVALID_BASE_URL')
    # HTTP is permitted only on loopback. Remote Sonarr requires HTTPS.
    if u.scheme == 'http':
        try:
            if not ipaddress.ip_address(u.hostname).is_loopback:
                raise SourceError('HTTP_REQUIRES_LOOPBACK')
        except ValueError as exc:
            raise SourceError('HTTP_REQUIRES_LOOPBACK') from exc
    return base.rstrip('/')


@dataclass(frozen=True)
class SonarrConfig:
    base_url: str
    api_key: str

    def __post_init__(self):
        _sonarr_base(self.base_url)
        if not isinstance(self.api_key, str) or len(self.api_key.strip()) < 12:
            raise SourceError('INVALID_API_KEY')


def fetch_sonarr_catalog(config, *, sonarr_series_id, transport=None):
    """Return raw catalog only after checking Sonarr series ID and episode ownership.

    Does not equate Sonarr IDs to AniList IDs, or absolute to canonical numbers.
    """
    if not isinstance(config, SonarrConfig) or not _positive(sonarr_series_id):
        raise SourceError('INVALID_REQUEST')
    base = _sonarr_base(config.base_url)
    headers = {'X-Api-Key': config.api_key, 'Accept': 'application/json'}
    series_request = urllib.request.Request(f'{base}/api/v3/series/{sonarr_series_id}', headers=headers)
    series = _read(series_request, transport)
    if not isinstance(series, dict) or series.get('id') != sonarr_series_id or not isinstance(series.get('title'), str) or not series['title'].strip():
        raise SourceError('SERIES_ID_MISMATCH')
    episodes_request = urllib.request.Request(f'{base}/api/v3/episode?seriesId={sonarr_series_id}', headers=headers)
    episodes = _read(episodes_request, transport)
    if not isinstance(episodes, list) or not episodes:
        raise SourceError('EMPTY_CATALOG')
    clean = []
    ids = set()
    for ep in episodes:
        if not isinstance(ep, dict) or not _positive(ep.get('id')) or ep['id'] in ids or ep.get('seriesId') != sonarr_series_id:
            raise SourceError('EPISODE_ID_MISMATCH')
        ids.add(ep['id'])
        season, number = ep.get('seasonNumber'), ep.get('episodeNumber')
        absolute = ep.get('absoluteEpisodeNumber')
        if type(season) is not int or season < 0 or type(number) is not int or number < 0:
            raise SourceError('INVALID_EPISODE_NUMBER')
        if absolute is not None and (type(absolute) is not int or absolute < 1):
            raise SourceError('INVALID_ABSOLUTE_NUMBER')
        clean.append({'id': ep['id'], 'season': season, 'episode': number, 'absolute': absolute})
    clean.sort(key=lambda x: x['id'])
    return {'sonarr_series_id': sonarr_series_id, 'series_title': series['title'], 'episodes': clean,
            'identity_only': True, 'canonical_mapping_authorized': False}


def capture_identity_evidence(*, anilist_id, sonarr_config, sonarr_series_id, transport=None, clock=None):
    """Capture independently fetched identity/catalog evidence; no cross-ID assertion.

    `transport` is a test seam, not a trust credential. Do not expose it to callers.
    """
    if not _positive(anilist_id):
        raise SourceError('INVALID_ANILIST_ID')
    if clock is None:
        clock = lambda: datetime.now(timezone.utc)
    # Restrict injected transport to tests / privileged adapter composition.
    try:
        ani = lookup_by_id(anilist_id, transport=transport)
    except MetadataLookupError as exc:
        raise SourceError('ANILIST_LOOKUP_FAILED') from exc
    sonarr = fetch_sonarr_catalog(sonarr_config, sonarr_series_id=sonarr_series_id, transport=transport)
    when = clock()
    if not isinstance(when, datetime) or when.tzinfo is None:
        raise SourceError('INVALID_CAPTURE_TIME')
    stamp = int(when.timestamp())
    if stamp <= 0:
        raise SourceError('INVALID_CAPTURE_TIME')
    payload = {'anilist': ani, 'sonarr': sonarr}
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True)
    return {'captured_at': stamp, 'sha256': hashlib.sha256(canonical.encode()).hexdigest(),
            'sources': payload, 'identity_only': True, 'canonical_mapping_authorized': False,
            'provenance_status': 'TRANSPORT_OBSERVED_NOT_CROSS_VERIFIED'}
