"""Read-only Prowlarr release search for backfill and continue.

Prowlarr only forwards the query to its indexers and returns raw results. This
module filters them by the verified anime's titles and episode number, reads
resolution from the title and ranks with DiscoveryPolicy. It never registers,
grabs or downloads anything; qBittorrent acquisition happens downstream.
"""
from dataclasses import dataclass, field
import http.client
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from src.nextgen.acquisition.qbittorrent import _NoRedirect, _json
from src.nextgen.acquisition.settings import endpoint
from src.nextgen.sonarr_episode import VerifiedEpisode

MAX_RESPONSE = 4 * 1024 * 1024
MAX_RELEASES = 1000
MAX_ALIASES = 3


class SearchReview(ValueError):
    reason_code = 'PROWLARR_SEARCH_REVIEW'
    def __init__(self): super().__init__('Prowlarr returned data that needs review.')


class SearchConfiguration(SearchReview):
    reason_code = 'PROWLARR_CONFIGURATION_INVALID'
    def __init__(self): ValueError.__init__(self, 'Configure Prowlarr before backfill search.')


class SearchUnauthorized(SearchConfiguration):
    reason_code = 'PROWLARR_AUTH_FAILED'
    def __init__(self): ValueError.__init__(self, 'Prowlarr rejected the API key.')


class SearchUnavailable(RuntimeError):
    reason_code = 'PROWLARR_UNAVAILABLE'
    def __init__(self): super().__init__('Prowlarr search is unavailable.')


class SearchTimeout(SearchUnavailable):
    reason_code = 'PROWLARR_SEARCH_TIMEOUT'
    def __init__(self): RuntimeError.__init__(self, 'Prowlarr search timed out.')


@dataclass(frozen=True)
class Options:
    base_url: str = field(repr=False)
    timeout_seconds: int = 60

    def __post_init__(self):
        try: object.__setattr__(self, 'base_url', endpoint(self.base_url))
        except ValueError: raise SearchConfiguration() from None
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 300:
            raise SearchConfiguration()

    @classmethod
    def capture(cls, configuration):
        return cls(configuration.value('prowlarr.base_url'),
                   configuration.value('prowlarr.timeout_seconds'))


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
        return cls(configuration.value('prowlarr.max_resolution'),
                   configuration.value('prowlarr.min_seeders'),
                   configuration.value('prowlarr.rank_by'))

    def accepts(self, release):
        return (release.eligible_for_handoff
                and 0 < release.resolution <= self.max_resolution
                and release.seeders is not None and release.seeders >= self.min_seeders)

    def rank(self, releases):
        """Accepted first, then resolution/seeders preference; ties keep input order."""
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
    """One matching indexer result, not an acquisition authorization."""
    title: str
    indexer: str
    resolution: int
    seeders: int | None
    size: int
    tvdb_episode_id: int
    info_hash: str | None
    magnet_url: str | None = field(default=None, repr=False)
    eligible_for_handoff: bool = False


@dataclass(frozen=True)
class SearchResult:
    tvdb_series_id: int
    tvdb_episode_id: int
    candidates: tuple[Release, ...]


@dataclass(frozen=True)
class EpisodeTarget:
    """Provider-verified placement of one TVDB episode (see providers.backfill_catalog)."""
    tvdb_episode: int
    status: str                  # SEARCHABLE, NOT_AIRED or MAPPING_MISSING
    anidb_episode: int | None = None
    tvdb_episode_id: int | None = None


@dataclass(frozen=True)
class EpisodeCatalog:
    titles: tuple[str, ...]
    episodes: dict = field(repr=False)   # tvdb episode number -> EpisodeTarget

    def target(self, number):
        return self.episodes.get(number) or EpisodeTarget(number, 'NOT_AIRED')


@dataclass(frozen=True)
class BackfillObservation:
    """Search summary only: no torrent link, verification, or acquisition permit."""
    number: int
    tvdb_episode_id: int | None
    status: str
    candidates: int = 0
    accepted: int = 0
    # In-memory only; magnets are never persisted from here.
    selection: object = field(default=None, repr=False, compare=False)


@dataclass(frozen=True)
class CandidateSelection:
    identity: VerifiedEpisode
    result: SearchResult = field(repr=False)
    release: Release = field(repr=False)
    policy: DiscoveryPolicy


RESOLUTION = re.compile(r'(?<![0-9])(480|540|576|720|1080|2160)[pi](?![A-Za-z0-9])', re.I)
UHD = re.compile(r'(?<![A-Za-z0-9])(?:4K|UHD)(?![A-Za-z0-9])', re.I)


def resolution(title):
    """Resolution declared in a release title, 0 when absent or contradictory."""
    found = {int(match.group(1)) for match in RESOLUTION.finditer(title)}
    if UHD.search(title): found.add(2160)
    return found.pop() if len(found) == 1 else 0


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


def search_aliases(titles):
    """Up to three distinct Latin-script titles; the AniDB main title comes first."""
    picked, seen = [], set()
    from src.nextgen.providers.parsing import norm
    for title in titles:
        if (type(title) is not str or not 2 <= len(title) <= 200 or not title.isascii()
                or any(ord(c) < 32 for c in title)):
            continue
        key = norm(title)
        if key and key not in seen:
            seen.add(key)
            picked.append(title)
        if len(picked) == MAX_ALIASES: break
    return tuple(picked)


def matches_episode(title, titles, target, season):
    """Exact normalized title alias plus the declared episode, as VERIFY_RELEASE reads it."""
    from src.nextgen.providers.parsing import norm, release_title
    from src.nextgen.providers.release_mapping import declared_episode
    from src.nextgen.release_contracts import ReleaseNotReady
    try:
        names, _ = release_title(title)
        origin, declared_season, number = declared_episode(title)
    except (ReleaseNotReady, ValueError, TypeError):
        return False
    wanted = {norm(name) for name in titles} - {''}
    if not wanted & {norm(name) for name in names}:
        return False
    if origin == 'tvdb':
        return (declared_season, number) == (season, target.tvdb_episode)
    return number == target.anidb_episode


def _release(row, titles, target, season):
    """A matching torrent result, or None for anything else."""
    if type(row) is not dict: raise SearchReview()
    title = row.get('title')
    if (type(title) is not str or not 1 <= len(title) <= 2048
            or any(ord(c) < 32 or ord(c) == 127 for c in title)):
        return None
    if row.get('protocol') not in ('torrent', None) or not matches_episode(title, titles, target, season):
        return None
    indexer = row.get('indexer') if type(row.get('indexer')) is str else ''
    seeders = row.get('seeders')
    seeders = seeders if type(seeders) is int and seeders >= 0 else None
    size = row.get('size') if type(row.get('size')) is int and row['size'] >= 0 else 0
    raw_hash = row.get('infoHash')
    info_hash = (raw_hash.lower() if type(raw_hash) is str
                 and re.fullmatch('[a-fA-F0-9]{40}', raw_hash) else None)
    magnet = None
    for source in (row.get('magnetUrl'), row.get('guid')):
        source_hash = _magnet_hash(source)
        if source_hash is None: continue
        if info_hash is not None and source_hash != info_hash:
            # Conflicting identities are never silently reconciled.
            return None
        info_hash, magnet = source_hash, source
        break
    if info_hash is not None and magnet is None:
        # Hash only: qBittorrent resolves it through DHT/PEX like a bare webhook hash.
        magnet = 'magnet:?xt=urn:btih:' + info_hash
    return Release(title[:2048], indexer[:256], resolution(title), seeders, size,
                   target.tvdb_episode_id, info_hash, magnet, info_hash is not None)


class Client:
    """GET-only Prowlarr transport plus a provider-backed episode catalog."""
    def __init__(self, options, api_key, *, catalog, transport=None, policy=None):
        if (type(options) is not Options or type(api_key) is not str or not api_key
                or len(api_key) > 1024 or any(ord(c) < 33 or ord(c) > 126 for c in api_key)
                or not callable(catalog)):
            raise SearchConfiguration()
        if policy is not None and type(policy) is not DiscoveryPolicy: raise SearchConfiguration()
        self.options, self._key = options, api_key
        self.catalog = catalog
        self.logger = None
        self.policy = policy or DiscoveryPolicy()
        opener = urllib.request.build_opener(_NoRedirect(), urllib.request.ProxyHandler({}))
        self._transport = transport or (lambda request, timeout: opener.open(request, timeout=timeout))

    @classmethod
    def from_context(cls, configuration, secrets, *, catalog, transport=None):
        try: key = secrets.prowlarr_api_key()
        except ValueError: raise SearchConfiguration() from None
        return cls(Options.capture(configuration), key, catalog=catalog, transport=transport,
                   policy=DiscoveryPolicy.capture(configuration))

    def _get(self, query):
        if type(query) is not str or not 1 <= len(query) <= 256:
            raise SearchReview()
        url = (self.options.base_url + '/api/v1/search?'
               + urllib.parse.urlencode({'query': query, 'type': 'search', 'limit': 100}))
        request = urllib.request.Request(url, method='GET', headers={
            'X-Api-Key': self._key, 'Accept': 'application/json',
            'User-Agent': 'AnimeDiscoveryNextGen/1'})
        started = time.monotonic()
        if self.logger is not None:
            self.logger.info('Prowlarr search started: query=%r timeout_seconds=%s',
                             query, self.options.timeout_seconds)
        try:
            with self._transport(request, self.options.timeout_seconds) as response:
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
        except TimeoutError:
            raise SearchTimeout() from None
        except urllib.error.URLError as exc:
            if isinstance(exc.reason, TimeoutError): raise SearchTimeout() from None
            raise SearchUnavailable() from None
        except (OSError, http.client.HTTPException):
            raise SearchUnavailable() from None
        if type(payload) is not list or len(payload) > MAX_RELEASES:
            raise SearchReview()
        if self.logger is not None:
            self.logger.info('Prowlarr search answered: results=%s elapsed_seconds=%.3f',
                             len(payload), time.monotonic() - started)
        return payload

    def _search(self, catalog, season, target):
        """All matching releases for one searchable episode, ranked by policy."""
        found, seen = [], set()
        for alias in search_aliases(catalog.titles):
            for row in self._get('%s %02d' % (alias, target.anidb_episode)):
                release = _release(row, catalog.titles, target, season)
                if release is None: continue
                key = release.info_hash or release.title
                if key in seen: continue
                seen.add(key)
                found.append(release)
        return self.policy.rank(found)

    def backfill(self, anidb_id, tvdb_series_id, season, numbers, *, reserved=(),
                 verified_ids=None, select_candidates=False):
        """One observation per requested episode. A missing release never fails the page."""
        if (type(anidb_id) is not int or anidb_id <= 0 or type(tvdb_series_id) is not int
                or tvdb_series_id <= 0 or type(season) is not int or season < 0
                or type(numbers) is not tuple or not 1 <= len(numbers) <= 4
                or any(type(n) is not int or n <= 0 for n in numbers)
                or len(set(numbers)) != len(numbers)
                or type(select_candidates) is not bool):
            raise SearchReview()
        verified_ids = verified_ids or {}
        catalog = self.catalog(anidb_id, tvdb_series_id, season)
        output = []
        for number in numbers:
            if number in reserved:
                output.append(BackfillObservation(number, verified_ids.get(number), 'IN_PROGRESS'))
                continue
            target = catalog.target(number)
            if target.status != 'SEARCHABLE':
                output.append(BackfillObservation(number, target.tvdb_episode_id, target.status))
                continue
            if verified_ids.get(number) not in (None, target.tvdb_episode_id):
                output.append(BackfillObservation(number, target.tvdb_episode_id, 'MAPPING_MISSING'))
                continue
            ranked = self._search(catalog, season, target)
            accepted = sum(self.policy.accepts(r) for r in ranked)
            choice = None
            if select_candidates and accepted:
                identity = VerifiedEpisode(tvdb_series_id, target.tvdb_episode_id, season, number)
                choice = CandidateSelection(identity,
                    SearchResult(tvdb_series_id, target.tvdb_episode_id, ranked),
                    ranked[0], self.policy)
            output.append(BackfillObservation(number, target.tvdb_episode_id,
                          'CANDIDATES' if ranked else 'NO_RESULTS', len(ranked), accepted, choice))
        return tuple(output)

    def search(self, anidb_id, identity):
        """Ranked releases for one previously selected episode (candidate fallback)."""
        if type(identity) is not VerifiedEpisode: raise SearchReview()
        catalog = self.catalog(anidb_id, identity.tvdb_series_id, identity.tvdb_season)
        target = catalog.target(identity.tvdb_episode)
        if target.status != 'SEARCHABLE' or target.tvdb_episode_id != identity.tvdb_episode_id:
            raise SearchReview()
        return SearchResult(identity.tvdb_series_id, identity.tvdb_episode_id,
                            self._search(catalog, identity.tvdb_season, target))
