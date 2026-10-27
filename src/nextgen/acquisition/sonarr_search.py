"""Read-only Sonarr v4 interactive episode search. Never grabs or registers media.

Sonarr ranks releases. NextGen verifies the exact TVDB identity and preserves
Sonarr's order; acquisition ownership remains outside this module.
"""
from dataclasses import dataclass, field
import http.client
import re
import urllib.error
import urllib.parse
import urllib.request

from src.nextgen.acquisition.qbittorrent import _NoRedirect, _json
from src.nextgen.acquisition.settings import endpoint
from src.nextgen.sonarr_episode import VerifiedEpisode, SonarrEpisodeMismatch, resolve_episode

MAX_RESPONSE = 4 * 1024 * 1024
MAX_RELEASES = 1000
INTERACTIVE_SEARCH_TIMEOUT_SECONDS = 180


class SearchReview(ValueError):
    reason_code = 'SONARR_DISCOVERY_REVIEW'
    def __init__(self): super().__init__('Sonarr discovery returned data requiring review.')


class SearchConfiguration(SearchReview):
    reason_code = 'SONARR_DISCOVERY_CONFIGURATION_INVALID'
    def __init__(self): ValueError.__init__(self, 'Configure Sonarr v4 before discovery.')


class SearchUnauthorized(SearchConfiguration):
    reason_code = 'SONARR_DISCOVERY_AUTH_FAILED'
    def __init__(self): ValueError.__init__(self, 'Sonarr discovery authentication failed.')


class SearchUnsupported(SearchReview):
    reason_code = 'SONARR_DISCOVERY_UNSUPPORTED'
    def __init__(self): ValueError.__init__(self, 'Sonarr v4 is required for discovery.')


class SearchNotFound(SearchReview):
    reason_code = 'SONARR_DISCOVERY_EPISODE_NOT_FOUND'
    def __init__(self): ValueError.__init__(self, 'The verified TVDB episode is not registered in Sonarr.')


class SearchUnavailable(RuntimeError):
    reason_code = 'SONARR_DISCOVERY_UNAVAILABLE'
    def __init__(self): super().__init__('Sonarr discovery is temporarily unavailable.')


@dataclass(frozen=True)
class Options:
    base_url: str = field(repr=False)
    timeout_seconds: int = 30

    def __post_init__(self):
        try: object.__setattr__(self, 'base_url', endpoint(self.base_url))
        except ValueError: raise SearchConfiguration() from None
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise SearchConfiguration()

    @classmethod
    def capture(cls, configuration):
        return cls(configuration.value('sonarr.base_url'),
                   configuration.value('sonarr.timeout_seconds'))


@dataclass(frozen=True)
class DiscoveryPolicy:
    """Local search preferences; never override identity/source validation."""
    max_resolution: int = 1080
    min_seeders: int = 5
    rank_by: str = 'resolution'

    def __post_init__(self):
        if (type(self.max_resolution) is not int or self.max_resolution not in (720, 1080, 2160)
                or type(self.min_seeders) is not int or not 0 <= self.min_seeders <= 1_000_000
                or type(self.rank_by) is not str or self.rank_by not in ('resolution', 'seeders')):
            raise SearchConfiguration()

    @classmethod
    def capture(cls, configuration):
        return cls(configuration.value('sonarr.discovery_max_resolution'),
                   configuration.value('sonarr.discovery_min_seeders'),
                   configuration.value('sonarr.discovery_rank_by'))

    def accepts(self, release):
        return (release.eligible_for_handoff
                and 0 < release.resolution <= self.max_resolution
                and release.seeders is not None and release.seeders >= self.min_seeders)

    def rank(self, releases):
        """Accepted candidates first, then deterministic preference order.

        Non-accepted rows are retained for diagnostics, never silently discarded.
        Original Sonarr order resolves full ties.
        """
        rows = tuple(releases)
        def key(item):
            index, release = item
            preference = ((release.resolution, release.seeders or 0)
                          if self.rank_by == 'resolution'
                          else (release.seeders or 0, release.resolution))
            return (not self.accepts(release), -preference[0], -preference[1], index)
        return tuple(release for _, release in sorted(enumerate(rows), key=key))


@dataclass(frozen=True)
class Release:
    """One original Sonarr-ranked result, not an acquisition authorization."""
    title: str
    indexer: str
    protocol: str
    quality: str
    resolution: int
    custom_format_score: int
    seeders: int | None
    leechers: int | None
    size: int
    approved: bool
    rejections: tuple[str, ...]
    mapped_episode_ids: tuple[int, ...]
    scope: str                  # exact, pack, mismatched, or unmapped
    info_hash: str | None
    magnet_url: str | None = field(default=None, repr=False)
    eligible_for_handoff: bool = False


@dataclass(frozen=True)
class SearchResult:
    series_id: int
    episode_id: int
    candidates: tuple[Release, ...]


@dataclass(frozen=True)
class BackfillObservation:
    """Search summary only: no torrent link, verification, or acquisition permit."""
    number: int
    sonarr_episode_id: int | None
    tvdb_episode_id: int | None
    status: str
    candidates: int = 0
    approved: int = 0
    exact: int = 0


def _positive(value):
    return type(value) is int and value > 0


def _text(value, limit=1024):
    if (type(value) is not str or len(value) > limit
            or any(ord(char) < 32 or ord(char) == 127 for char in value)):
        raise SearchReview()
    return value


def _nonnegative(value):
    if type(value) is not int or value < 0: raise SearchReview()
    return value


def _optional_count(value):
    return None if value is None else _nonnegative(value)


def _magnet_hash(uri):
    if not uri: return None
    if type(uri) is not str or len(uri) > 8192 or not uri.startswith('magnet:?'):
        return None
    try:
        values = urllib.parse.parse_qs(urllib.parse.urlsplit(uri).query)
        xt = values.get('xt', [])
        if len(xt) != 1: return None
        match = re.fullmatch(r'urn:btih:([a-fA-F0-9]{40})', xt[0], flags=re.IGNORECASE)
        return match.group(1).lower() if match else None
    except ValueError:
        return None


def _release(row, series_id, episode_id, identity):
    if type(row) is not dict: raise SearchReview()
    title = _text(row.get('title'), 2048)
    indexer = _text(row.get('indexer') or '', 256)
    protocol = _text(row.get('protocol'), 32)
    quality = row.get('quality')
    if type(quality) is not dict or type(quality.get('quality')) is not dict:
        raise SearchReview()
    name = _text(quality['quality'].get('name'), 128)
    resolution = _nonnegative(quality['quality'].get('resolution'))
    score = row.get('customFormatScore', 0)
    if type(score) is not int: raise SearchReview()
    approved = row.get('approved')
    rejected = row.get('rejected')
    if type(approved) is not bool or type(rejected) is not bool: raise SearchReview()
    rejections = row.get('rejections') or []
    if (type(rejections) is not list or len(rejections) > 100
            or any(type(reason) is not str for reason in rejections)):
        raise SearchReview()
    reasons = tuple(_text(reason, 1024) for reason in rejections)
    mapped = row.get('mappedEpisodeInfo') or []
    if type(mapped) is not list or len(mapped) > 100:
        raise SearchReview()
    episode_ids = []
    for entry in mapped:
        if type(entry) is not dict or not _positive(entry.get('id')):
            raise SearchReview()
        episode_ids.append(entry['id'])
    ids = tuple(episode_ids)
    match_series = row.get('mappedSeriesId') == series_id
    matching = [item for item in mapped if item['id'] == episode_id]
    verified_placement = (len(matching) == 1
                          and matching[0].get('seasonNumber') == identity.tvdb_season
                          and matching[0].get('episodeNumber') == identity.tvdb_episode)
    mapped_season = row.get('mappedSeasonNumber')
    mapped_numbers = row.get('mappedEpisodeNumbers')
    if (mapped_season is not None and mapped_season != identity.tvdb_season
            or mapped_numbers is not None and
            (type(mapped_numbers) is not list or identity.tvdb_episode not in mapped_numbers)):
        verified_placement = False
    if not match_series or ids and not verified_placement:
        scope = 'mismatched'
    elif not ids:
        scope = 'unmapped'
    elif len(ids) != 1 or row.get('fullSeason') is True:
        scope = 'pack'
    else:
        scope = 'exact'
    raw_hash = row.get('infoHash')
    info_hash = raw_hash.lower() if type(raw_hash) is str and re.fullmatch('[a-fA-F0-9]{40}', raw_hash) else None
    # A Sonarr/Prowlarr torrent GUID can itself be the usable magnet.
    # Never treat an HTTP GUID as an acquisition URL or follow it here.
    raw_magnet = row.get('magnetUrl')
    guid = row.get('guid')
    sources = (raw_magnet, guid)
    magnet = None
    for source in sources:
        source_hash = _magnet_hash(source)
        if source_hash is None:
            continue
        if info_hash is not None and source_hash != info_hash:
            # Conflicting identities cannot be silently reconciled.
            magnet = None
            break
        if magnet is not None and _magnet_hash(magnet) != source_hash:
            magnet = None
            break
        magnet = source
    if info_hash is None:
        info_hash = _magnet_hash(magnet)
    # This is discovery usability, not authorization to submit a torrent.
    # Sonarr's custom formats, profile and file-cutoff decisions are diagnostics.
    handoff = (scope == 'exact' and protocol == 'torrent'
               and bool(info_hash) and bool(magnet))
    return Release(title, indexer, protocol, name, resolution, score,
                   _optional_count(row.get('seeders')), _optional_count(row.get('leechers')),
                   _nonnegative(row.get('size')), approved, reasons, ids, scope,
                   info_hash, magnet, handoff)


class Client:
    """Strict GET-only transport with injected fake transport for offline tests."""
    def __init__(self, options, api_key, *, transport=None, policy=None):
        if (type(options) is not Options or type(api_key) is not str or not api_key
                or len(api_key) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in api_key)):
            raise SearchConfiguration()
        if policy is not None and type(policy) is not DiscoveryPolicy: raise SearchConfiguration()
        self.options, self._key = options, api_key
        self.policy = policy or DiscoveryPolicy()
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))
        self._transport = transport or (lambda request, timeout: opener.open(request, timeout=timeout))

    @classmethod
    def from_context(cls, configuration, secrets, *, transport=None):
        try: key = secrets.sonarr_api_key()
        except ValueError: raise SearchConfiguration() from None
        return cls(Options.capture(configuration), key, transport=transport,
                   policy=DiscoveryPolicy.capture(configuration))

    def _get(self, path, query=None):
        if path not in ('system/status', 'series', 'episode', 'release'):
            raise SearchReview()
        url = self.options.base_url + '/api/v3/' + path
        if query:
            if (path == 'series' and set(query) != {'tvdbId'}
                    or path == 'episode' and set(query) != {'seriesId'}
                    or path == 'release' and set(query) != {'episodeId'}
                    or path == 'system/status'):
                raise SearchReview()
            if any(not _positive(v) for v in query.values()): raise SearchReview()
            url += '?' + urllib.parse.urlencode(query)
        elif path != 'system/status':
            raise SearchReview()
        request = urllib.request.Request(url, method='GET', headers={
            'X-Api-Key': self._key, 'Accept': 'application/json',
            'User-Agent': 'AnimeDiscoveryNextGen/1'
        })
        try:
            with self._transport(request, max(self.options.timeout_seconds, INTERACTIVE_SEARCH_TIMEOUT_SECONDS) if path == 'release' else self.options.timeout_seconds) as response:
                code = response.getcode()
                if code in (401, 403): raise SearchUnauthorized()
                if code == 429 or code >= 500: raise SearchUnavailable()
                if code != 200: raise SearchReview()
                raw = response.read(MAX_RESPONSE + 1)
                if type(raw) is not bytes or len(raw) > MAX_RESPONSE: raise SearchReview()
                try: payload = _json(raw)
                except ValueError: raise SearchReview() from None
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            if code in (401, 403): raise SearchUnauthorized() from None
            if code == 429 or code >= 500: raise SearchUnavailable() from None
            raise SearchReview() from None
        except (OSError, TimeoutError, urllib.error.URLError, http.client.HTTPException):
            raise SearchUnavailable() from None
        if path == 'system/status':
            if type(payload) is not dict: raise SearchReview()
        elif (type(payload) is not list or len(payload) > (MAX_RELEASES if path == 'release' else 10000)
              or any(type(row) is not dict for row in payload)):
            raise SearchReview()
        return payload


    def backfill(self, tvdb_series_id, season, numbers, *, reserved=(), verified_ids=None):
        """Read-only bounded positional lookup for a frozen backfill window.

        Sonarr episode IDs are untrusted discovery hints unless independently
        verified via verified_ids. Never passes an unverified episode to an
        acquisition pipeline or turns interactive results into downloads.
        """
        if (not _positive(tvdb_series_id) or type(season) is not int or season < 0
                or type(numbers) is not tuple or not 1 <= len(numbers) <= 4
                or any(not _positive(n) for n in numbers) or len(set(numbers)) != len(numbers)
                or type(reserved) not in (tuple, frozenset)
                or any(not _positive(n) for n in reserved)
                or type(verified_ids) not in (dict, type(None))):
            raise SearchReview()
        verified_ids = verified_ids or {}
        if any(not _positive(n) or not _positive(v) for n, v in verified_ids.items()):
            raise SearchReview()
        status = self._get('system/status')
        version = status.get('version')
        if type(version) is not str or not re.fullmatch(r'4\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', version):
            raise SearchUnsupported()
        series = [row for row in self._get('series', {'tvdbId': tvdb_series_id})
                  if row.get('tvdbId') == tvdb_series_id]
        if not series: raise SearchNotFound()
        if len(series) != 1 or not _positive(series[0].get('id')): raise SearchReview()
        sid = series[0]['id']
        episodes = self._get('episode', {'seriesId': sid})
        rows = {}
        for row in episodes:
            if row.get('seriesId') != sid: raise SearchReview()
            if row.get('seasonNumber') == season and type(row.get('episodeNumber')) is int:
                num = row['episodeNumber']
                if num in rows: raise SearchReview()
                rows[num] = row
        output = []
        for number in numbers:
            if number in reserved:
                output.append(BackfillObservation(number, None, verified_ids.get(number), 'IN_PROGRESS'))
                continue
            ep = rows.get(number)
            if ep is None:
                output.append(BackfillObservation(number, None, verified_ids.get(number), 'NOT_LISTED'))
                continue
            eid, tid = ep.get('id'), ep.get('tvdbId')
            if not _positive(eid): raise SearchReview()
            if not _positive(tid):
                output.append(BackfillObservation(number, eid, None, 'IDENTITY_UNKNOWN'))
                continue
            if verified_ids.get(number) not in (None, tid):
                output.append(BackfillObservation(number, eid, tid, 'IDENTITY_CONFLICT'))
                continue
            if type(ep.get('hasFile')) is not bool: raise SearchReview()
            if ep['hasFile']:
                output.append(BackfillObservation(number, eid, tid, 'HAS_FILE'))
                continue
            identity = VerifiedEpisode(tvdb_series_id, tid, season, number)
            results = tuple(_release(r, sid, eid, identity)
                            for r in self._get('release', {'episodeId': eid}))
            approved = sum(r.approved and not r.rejections and r.scope == 'exact' for r in results)
            exact = sum(self.policy.accepts(r) for r in results)
            output.append(BackfillObservation(number, eid, tid,
                          'CANDIDATES' if results else 'NO_RESULTS',
                          len(results), approved, exact))
        return tuple(output)

    def search(self, identity: VerifiedEpisode):
        """Ranked results for a previously verified TVDB episode; never POSTs."""
        if type(identity) is not VerifiedEpisode: raise SearchReview()
        status = self._get('system/status')
        version = status.get('version')
        if type(version) is not str or not re.fullmatch(r'4\.[0-9]+\.[0-9]+(?:\.[0-9]+)?', version):
            raise SearchUnsupported()
        series = [row for row in self._get('series', {'tvdbId': identity.tvdb_series_id})
                  if row.get('tvdbId') == identity.tvdb_series_id]
        if not series: raise SearchNotFound()
        if len(series) != 1 or not _positive(series[0].get('id')): raise SearchReview()
        sid = series[0]['id']
        episodes = self._get('episode', {'seriesId': sid})
        try: _, eid = resolve_episode(identity, series[0], episodes)
        except SonarrEpisodeMismatch: raise SearchNotFound() from None
        rows = self._get('release', {'episodeId': eid})
        return SearchResult(sid, eid, self.policy.rank(
            _release(row, sid, eid, identity) for row in rows))
