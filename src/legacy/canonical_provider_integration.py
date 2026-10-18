"""Read-only Sonarr + TVmaze canonical episode comparison.

TVmaze is an independently maintained episode catalog, but its TVDB lookup is
only an identity cross-reference. Agreement is NOT release-to-file proof.
No approval, controller database, or write API is exposed here.
"""
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class MappingBlocked(ValueError):
    pass


@dataclass(frozen=True)
class EpisodePair:
    season: int
    episode: int
    sonarr_title: str
    tvmaze_title: str


class TVmazeReadOnly:
    """Fetch a TVmaze show by TVDB ID and its regular episode catalog over TLS."""
    BASE = 'https://api.tvmaze.com'

    def __init__(self, *, timeout=8, opener=None):
        self.timeout = timeout
        self._opener = opener or urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=ssl.create_default_context()),
            urllib.request.ProxyHandler({}))

    def _get(self, path):
        if not path.startswith('/') or '?' in path or '#' in path or '//' in path:
            raise MappingBlocked('INVALID_PROVIDER_PATH')
        req = urllib.request.Request(self.BASE + path, headers={'Accept': 'application/json', 'User-Agent': 'anime-discovery-readonly/1'})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                if resp.geturl() != self.BASE + path:
                    raise MappingBlocked('PROVIDER_REDIRECT_BLOCKED')
                if resp.status != 200:
                    raise MappingBlocked('PROVIDER_HTTP_ERROR')
                return json.loads(resp.read(2_000_001).decode('utf-8'))
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if isinstance(exc, MappingBlocked):
                raise
            raise MappingBlocked('PROVIDER_UNAVAILABLE') from exc

    def show_by_tvdb(self, tvdb_id):
        if type(tvdb_id) is not int or tvdb_id <= 0:
            raise MappingBlocked('INVALID_TVDB_ID')
        # TVmaze API uses query for lookup; URL is built only from validated int.
        path = '/lookup/shows?thetvdb={}'.format(tvdb_id)
        req = urllib.request.Request(self.BASE + path, headers={'Accept': 'application/json', 'User-Agent': 'anime-discovery-readonly/1'})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                final = urllib.parse.urlsplit(resp.geturl())
                original = urllib.parse.urlsplit(self.BASE + path)
                direct = final == original
                canonical = (final.scheme == 'https' and final.netloc == 'api.tvmaze.com'
                             and not final.query and not final.fragment
                             and final.path.startswith('/shows/')
                             and final.path[len('/shows/'):].isdigit()
                             and int(final.path[len('/shows/'):]) > 0)
                if resp.status != 200 or not (direct or canonical):
                    raise MappingBlocked('PROVIDER_REDIRECT_OR_STATUS')
                show = json.loads(resp.read(1_000_001).decode('utf-8'))
                if canonical and show.get('id') != int(final.path[len('/shows/'):]):
                    raise MappingBlocked('REDIRECT_SHOW_ID_MISMATCH')
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            if isinstance(exc, MappingBlocked):
                raise
            raise MappingBlocked('TVMAZE_LOOKUP_FAILED') from exc
        if not isinstance(show, dict) or type(show.get('id')) is not int or show['id'] <= 0:
            raise MappingBlocked('INVALID_TVMAZE_SHOW')
        externals = show.get('externals')
        if not isinstance(externals, dict) or str(externals.get('thetvdb')) != str(tvdb_id):
            raise MappingBlocked('TVDB_CROSS_REFERENCE_MISMATCH')
        return show

    def episodes(self, show_id):
        if type(show_id) is not int or show_id <= 0:
            raise MappingBlocked('INVALID_TVMAZE_ID')
        data = self._get('/shows/{}/episodes'.format(show_id))
        if not isinstance(data, list):
            raise MappingBlocked('INVALID_TVMAZE_EPISODES')
        return data


def compare_season_one(sonarr_series, sonarr_episodes, tvmaze_show, tvmaze_episodes, *, limit=6):
    """Produce candidate pairs, never authorize metadata mapping or user Keep."""
    if type(limit) is not int or not 1 <= limit <= 6:
        raise MappingBlocked('INVALID_TRIAL_LIMIT')
    if not isinstance(sonarr_series, dict) or type(sonarr_series.get('tvdbId')) is not int or sonarr_series['tvdbId'] <= 0:
        raise MappingBlocked('SONARR_TVDB_ID_REQUIRED')
    if not isinstance(tvmaze_show, dict) or not isinstance(tvmaze_show.get('externals'), dict) or str(tvmaze_show['externals'].get('thetvdb')) != str(sonarr_series['tvdbId']):
        raise MappingBlocked('IDENTITY_CONFLICT')
    if not isinstance(sonarr_episodes, list) or not isinstance(tvmaze_episodes, list):
        raise MappingBlocked('EPISODE_LISTS_REQUIRED')
    def indexed(items, source):
        out = {}
        for row in items:
            if not isinstance(row, dict):
                raise MappingBlocked('INVALID_{}_EPISODE'.format(source))
            season = row.get('seasonNumber' if source == 'SONARR' else 'season')
            number = row.get('episodeNumber' if source == 'SONARR' else 'number')
            if type(season) is not int or type(number) is not int:
                raise MappingBlocked('INVALID_{}_NUMBER'.format(source))
            if season != 1 or number < 1 or number > limit:
                continue
            if source == 'TVMAZE' and row.get('type', 'regular') != 'regular':
                raise MappingBlocked('NONREGULAR_TVMAZE_EPISODE')
            title = row.get('title' if source == 'SONARR' else 'name')
            if not isinstance(title, str) or not title.strip():
                raise MappingBlocked('MISSING_{}_TITLE'.format(source))
            if number in out:
                raise MappingBlocked('DUPLICATE_{}_NUMBER'.format(source))
            out[number] = title.strip()
        return out
    s = indexed(sonarr_episodes, 'SONARR')
    t = indexed(tvmaze_episodes, 'TVMAZE')
    if not s or not t:
        raise MappingBlocked('NO_SEASON_ONE_DATA')
    prefix = []
    for number in range(1, limit + 1):
        if number not in s or number not in t:
            break
        prefix.append(EpisodePair(1, number, s[number], t[number]))
    if not prefix or len(prefix) != min(limit, len(s), len(t)):
        # Gaps are not an acceptable way to claim a complete prefix.
        raise MappingBlocked('NONCONTIGUOUS_OR_CONFLICTING_PREFIX')
    return {'status': 'CANDIDATE_ONLY', 'tvdb_id': sonarr_series['tvdbId'],
            'tvmaze_id': tvmaze_show['id'], 'prefix': [p.__dict__ for p in prefix],
            'canonical_mapping_authorized': False, 'release_mapping_verified': False,
            'keep_or_reject_authorized': False,
            'reason': 'CATALOG_AGREEMENT_IS_NOT_RELEASE_FILE_PROVENANCE'}
