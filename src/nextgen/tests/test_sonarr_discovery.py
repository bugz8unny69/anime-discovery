"""Offline read-only Sonarr discovery contract tests. No service or CI required."""
import io
import json
import unittest
import urllib.error
from urllib.parse import urlsplit, parse_qs

from src.nextgen.acquisition.sonarr_search import (
    Client, Options, SearchConfiguration, SearchNotFound, SearchReview,
    SearchUnauthorized, SearchUnavailable, SearchUnsupported, MAX_RESPONSE,
)
from src.nextgen.keep_selection import KeepSelection, KeepSelectionInvalid
from src.nextgen.sonarr_episode import VerifiedEpisode, SonarrEpisodeMismatch, resolve_episode

HASH = 'a' * 40
OTHER_HASH = 'b' * 40
ID = VerifiedEpisode(100, 200, 1, 10)


class Response(io.BytesIO):
    def __init__(self, data, code=200, *, raw=False):
        super().__init__(data if raw else json.dumps(data).encode())
        self.code = code

    def getcode(self):
        return self.code


def release(**changes):
    base = {
        'title': 'Example S01E10 1080p', 'indexer': 'Indexer One', 'protocol': 'torrent',
        'quality': {'quality': {'name': 'WEBDL-1080p', 'resolution': 1080}},
        'customFormatScore': 80, 'seeders': 50, 'leechers': 2, 'size': 300000000,
        'approved': True, 'rejected': False, 'rejections': [],
        'mappedSeriesId': 11,
        'mappedEpisodeInfo': [{'id': 22, 'seasonNumber': 1, 'episodeNumber': 10}],
        'fullSeason': False, 'infoHash': HASH,
        'magnetUrl': 'magnet:?xt=urn:btih:' + HASH,
    }
    base.update(changes)
    return base


class FakeSonarr:
    def __init__(self, *, releases=None):
        self.series = [{'id': 11, 'tvdbId': 100, 'seriesType': 'anime'}]
        self.episodes = [{'id': 22, 'seriesId': 11, 'tvdbId': 200,
                          'seasonNumber': 1, 'episodeNumber': 10}]
        self.releases = releases if releases is not None else [release()]
        self.version = '4.0.16.1'
        self.visited = []
        self.error = None

    def __call__(self, request, timeout):
        self.visited.append(request.full_url)
        assert request.get_method() == 'GET'
        assert request.data is None
        assert request.get_header('X-api-key') == 'private-sonarr-key'
        assert timeout == 13
        url = urlsplit(request.full_url)
        assert url.netloc == 'sonarr.invalid'
        path = url.path.removeprefix('/api/v3/')
        params = parse_qs(url.query)
        if self.error:
            if isinstance(self.error, int):
                raise urllib.error.HTTPError(request.full_url, self.error, 'fail', {}, io.BytesIO())
            raise self.error
        if path == 'system/status':
            assert not params
            return Response({'version': self.version})
        if path == 'series':
            assert params == {'tvdbId': ['100']}
            return Response(self.series)
        if path == 'episode':
            assert params == {'seriesId': ['11']}
            return Response(self.episodes)
        if path == 'release':
            assert params == {'episodeId': ['22']}
            return Response(self.releases)
        raise AssertionError('Unsupported HTTP operation: ' + path)


def client(fake=None):
    fake = fake or FakeSonarr()
    return Client(Options('http://sonarr.invalid', 13), 'private-sonarr-key', transport=fake), fake


class SonarrDiscoveryTests(unittest.TestCase):
    def test_ranked_release_results_are_read_only_and_preserve_original_order(self):
        fake = FakeSonarr(releases=[
            release(title='First - rejected', approved=False, rejected=True,
                    rejections=['Quality not wanted']),
            release(title='Second - approved', customFormatScore=120, seeders=9),
        ])
        selected = client(fake)[0].search(ID)
        self.assertEqual((selected.series_id, selected.episode_id), (11, 22))
        self.assertEqual([c.title for c in selected.candidates],
                         ['First - rejected', 'Second - approved'])
        self.assertEqual(selected.candidates[0].rejections, ('Quality not wanted',))
        self.assertFalse(selected.candidates[0].eligible_for_handoff)
        self.assertTrue(selected.candidates[1].eligible_for_handoff)
        self.assertEqual(selected.candidates[1].resolution, 1080)
        self.assertEqual(selected.candidates[1].seeders, 9)
        self.assertEqual([urlsplit(v).path for v in fake.visited],
                         ['/api/v3/system/status', '/api/v3/series',
                          '/api/v3/episode', '/api/v3/release'])

    def test_does_not_create_missing_series(self):
        c, fake = client()
        fake.series = []
        with self.assertRaises(SearchNotFound): c.search(ID)
        self.assertEqual(len(fake.visited), 2)

    def test_rejects_missing_duplicate_or_wrong_episode_mapping(self):
        for episodes in ([], [
            {'id': 22, 'seriesId': 11, 'tvdbId': 999, 'seasonNumber': 1, 'episodeNumber': 10}
        ], [
            {'id': 22, 'seriesId': 11, 'seasonNumber': 1, 'episodeNumber': 10},
            {'id': 23, 'seriesId': 11, 'seasonNumber': 1, 'episodeNumber': 10},
        ]):
            c, fake = client()
            fake.episodes = episodes
            with self.subTest(episodes=episodes), self.assertRaises(SearchNotFound):
                c.search(ID)
            self.assertEqual(len(fake.visited), 3)

    def test_wrong_or_ambiguous_series_rejected_without_search(self):
        for series in ([{'id': 11, 'tvdbId': 999}], [
            {'id': 11, 'tvdbId': 100}, {'id': 12, 'tvdbId': 100}
        ]):
            c, fake = client()
            fake.series = series
            with self.subTest(series=series), self.assertRaises((SearchReview, SearchNotFound)):
                c.search(ID)
            self.assertEqual(len(fake.visited), 2)

    def test_packs_mismatches_and_unmapped_are_not_eligible(self):
        c, _ = client(FakeSonarr(releases=[
            release(title='Pack', mappedEpisodeInfo=[
                {'id': 22, 'seasonNumber': 1, 'episodeNumber': 10},
                {'id': 23, 'seasonNumber': 1, 'episodeNumber': 11}]),
            release(title='Different', mappedEpisodeInfo=[
                {'id': 99, 'seasonNumber': 1, 'episodeNumber': 9}]),
            release(title='Unmapped', mappedEpisodeInfo=[]),
            release(title='Other series', mappedSeriesId=12),
            release(title='Full season', fullSeason=True),
        ]))
        rows = c.search(ID).candidates
        self.assertEqual([r.scope for r in rows],
                         ['pack', 'mismatched', 'unmapped', 'mismatched', 'pack'])
        self.assertFalse(any(r.eligible_for_handoff for r in rows))

    def test_no_magnet_no_hash_and_conflicting_hash_never_authorize_handoff(self):
        c, _ = client(FakeSonarr(releases=[
            release(title='No magnet', magnetUrl=None),
            release(title='Wrong infohash', infoHash=OTHER_HASH),
            release(title='No source', infoHash=None, magnetUrl=None),
            release(title='Usenet', protocol='usenet'),
        ]))
        rows = c.search(ID).candidates
        self.assertTrue(all(not r.eligible_for_handoff for r in rows))
        self.assertIsNone(rows[0].magnet_url)
        self.assertIsNone(rows[1].magnet_url)
        self.assertIsNone(rows[2].info_hash)

    def test_does_not_leak_secret_or_magnet_via_repr(self):
        c, _ = client()
        row = c.search(ID).candidates[0]
        self.assertNotIn('private-sonarr-key', repr(c))
        self.assertNotIn('magnet:', repr(row))

    def test_authenticated_configuration_from_existing_settings(self):
        class Configuration:
            def value(self, field):
                return {'sonarr.base_url': 'http://sonarr.invalid',
                        'sonarr.timeout_seconds': 13}[field]
        class Secrets:
            def sonarr_api_key(self):
                return 'private-sonarr-key'
        fake = FakeSonarr()
        c = Client.from_context(Configuration(), Secrets(), transport=fake)
        self.assertEqual(c.search(ID).episode_id, 22)

    def test_invalid_configuration_and_non_v4_server(self):
        for url in ('', 'ftp://sonarr.invalid', 'http://user:pass@sonarr.invalid'):
            with self.subTest(url=url), self.assertRaises(SearchConfiguration):
                Options(url, 13)
        with self.assertRaises(SearchConfiguration):
            Client(Options('http://sonarr.invalid'), '')
        with self.assertRaises(SonarrEpisodeMismatch):
            VerifiedEpisode(100, 200, -1, 10)
        c, fake = client()
        fake.version = '5.0.0.0'
        with self.assertRaises(SearchUnsupported): c.search(ID)
        self.assertEqual(len(fake.visited), 1)

    def test_transport_failures(self):
        for status, expected in ((401, SearchUnauthorized), (403, SearchUnauthorized),
                                 (429, SearchUnavailable), (503, SearchUnavailable),
                                 (404, SearchReview)):
            c, fake = client()
            fake.error = status
            with self.subTest(code=status), self.assertRaises(expected):
                c.search(ID)
        c, fake = client()
        fake.error = urllib.error.URLError('connection refused')
        with self.assertRaises(SearchUnavailable): c.search(ID)

    def test_bounded_bad_json_and_duplicate_keys(self):
        for raw in (b'{bad json', b'{"version":"4.0.16.1","version":"4.0.16.1"}',
                    b'x' * (MAX_RESPONSE + 1)):
            c, fake = client()
            def oversize(request, timeout):
                return Response(raw, raw=True)
            c._transport = oversize
            with self.subTest(length=len(raw)), self.assertRaises(SearchReview):
                c.search(ID)
        c, _ = client(FakeSonarr(releases=[release() for _ in range(1001)]))
        with self.assertRaises(SearchReview): c.search(ID)

    def test_malformed_release_is_not_approved(self):
        for changes in ({'seeders': -2}, {'quality': {}}, {'approved': 'yes'},
                        {'mappedEpisodeInfo': [{'id': '22'}]}):
            c, _ = client(FakeSonarr(releases=[release(**changes)]))
            with self.subTest(changes=changes), self.assertRaises(SearchReview):
                c.search(ID)

    def test_keep_reuses_identical_verified_episode_mapping(self):
        selection = KeepSelection(1, 2, 100, 200, 1, 10, 1, '/tmp/staging', 'episode.mkv')
        series = {'id': 11, 'tvdbId': 100}
        episodes = [{'id': 22, 'seriesId': 11, 'seasonNumber': 1,
                     'episodeNumber': 10, 'tvdbId': 200}]
        self.assertEqual(resolve_episode(ID, series, episodes),
                         selection.match_sonarr_episode(series, episodes))
        with self.assertRaises(KeepSelectionInvalid):
            selection.match_sonarr_episode(series, [])
