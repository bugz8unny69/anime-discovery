"""Offline read-only Sonarr discovery contract tests. No service or CI required."""
import io
import json
import unittest
import urllib.error
from urllib.parse import urlsplit, parse_qs

from src.nextgen.acquisition.sonarr_search import (
    Client, Options, DiscoveryPolicy, SearchConfiguration, SearchNotFound, SearchReview,
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
        assert timeout == (180 if urlsplit(request.full_url).path == '/api/v3/release' else 13)
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
        self.assertTrue(selected.candidates[0].eligible_for_handoff)
        self.assertTrue(selected.candidates[1].eligible_for_handoff)
        self.assertEqual(selected.candidates[1].resolution, 1080)
        self.assertEqual(selected.candidates[1].seeders, 9)
        self.assertEqual([urlsplit(v).path for v in fake.visited],
                         ['/api/v3/system/status', '/api/v3/series',
                          '/api/v3/episode', '/api/v3/release'])

    def test_backfill_selection_only_for_independently_verified_episode(self):
        fake = FakeSonarr(releases=[release(approved=False, rejected=True,
                                           rejections=['Sonarr profile rejected'])])
        fake.episodes[0]['hasFile'] = False
        discovery = client(fake)[0]
        unchecked = discovery.backfill(100, 1, (10,), select_candidates=True)
        self.assertIsNotNone(unchecked[0].selection)
        # Provisional Sonarr hints require provider re-verification before
        # the original reservation and acquisition stages can proceed.
        verified = discovery.backfill(100, 1, (10,), verified_ids={10: 200},
                                      select_candidates=True)
        self.assertEqual(verified[0].exact, 1)
        choice = verified[0].selection
        self.assertIsNotNone(choice)
        self.assertFalse(choice.release.approved)
        self.assertEqual(choice.identity, ID)
        self.assertEqual(choice.release.info_hash, HASH)
        self.assertNotIn('magnet:', repr(verified[0]))

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
            # A present series with a bad episode mapping is review, never "series missing".
            with self.subTest(episodes=episodes), self.assertRaises(SearchReview) as raised:
                c.search(ID)
            self.assertNotIsInstance(raised.exception, SearchNotFound)
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
            release(title='Wrong TVDB placement', mappedEpisodeInfo=[
                {'id': 22, 'seasonNumber': 2, 'episodeNumber': 10}]),
            release(title='Conflicting mapped number', mappedEpisodeNumbers=[12]),
        ]))
        rows = c.search(ID).candidates
        self.assertEqual([r.scope for r in rows],
                         ['pack', 'mismatched', 'unmapped', 'mismatched', 'pack',
                          'mismatched', 'mismatched'])
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


    def test_guid_magnet_consistency_and_sonarr_rejected_discovery(self):
        magnet = 'magnet:?xt=urn:btih:' + HASH + '&tr=udp%3A%2F%2Ftracker.example%3A80'
        rows = client(FakeSonarr(releases=[
            release(title='Rejected', approved=False, rejected=True,
                    rejections=['Custom format minimum'], guid=magnet, magnetUrl=''),
            release(title='Conflict', guid='magnet:?xt=urn:btih:' + OTHER_HASH, magnetUrl=''),
            release(title='HTTP', guid='https://example.invalid/torrent', magnetUrl=''),
        ]))[0].search(ID).candidates
        by_title = {r.title: r for r in rows}
        self.assertTrue(by_title['Rejected'].eligible_for_handoff)
        self.assertEqual(by_title['Rejected'].magnet_url, magnet)
        self.assertFalse(by_title['Conflict'].eligible_for_handoff)
        self.assertFalse(by_title['HTTP'].eligible_for_handoff)

    def test_local_resolution_and_seeder_ranking(self):
        rows = [
            release(title='720 many peers', quality={'quality': {'name': 'HDTV-720p', 'resolution': 720}}, seeders=100),
            release(title='1080 fewer peers', seeders=15),
            release(title='2160 above ceiling', quality={'quality': {'name': 'WEBDL-2160p', 'resolution': 2160}}, seeders=300),
            release(title='1080 below seeder minimum', seeders=2),
        ]
        def ranked(policy):
            return Client(Options('http://sonarr.invalid', 13), 'private-sonarr-key',
                          transport=FakeSonarr(releases=rows), policy=policy).search(ID).candidates
        a = ranked(DiscoveryPolicy())
        b = ranked(DiscoveryPolicy(rank_by='seeders'))
        self.assertEqual([r.title for r in a[:2]], ['1080 fewer peers', '720 many peers'])
        self.assertEqual([r.title for r in b[:2]], ['720 many peers', '1080 fewer peers'])
        self.assertEqual(sum(DiscoveryPolicy().accepts(r) for r in a), 2)
        for params in ({'max_resolution': 1440}, {'max_resolution': True},
                       {'min_seeders': -1}, {'rank_by': 'sonarr'}):
            with self.subTest(params=params), self.assertRaises(SearchConfiguration):
                DiscoveryPolicy(**params)


    def test_configuration_metadata_exposes_validated_local_discovery_preferences(self):
        from src.nextgen.configuration_schema import ConfigurationSnapshot, ConfigurationError, FIELDS
        self.assertEqual(FIELDS['sonarr.discovery_max_resolution'].default, 1080)
        self.assertEqual(FIELDS['sonarr.discovery_min_seeders'].default, 5)
        self.assertEqual(FIELDS['sonarr.discovery_rank_by'].default, 'resolution')
        snapshot = ConfigurationSnapshot(1, {'sonarr': {
            'discovery_max_resolution': 720,
            'discovery_min_seeders': 0,
            'discovery_rank_by': 'seeders',
        }})
        policy = DiscoveryPolicy.capture(snapshot)
        self.assertEqual((policy.max_resolution, policy.min_seeders, policy.rank_by),
                         (720, 0, 'seeders'))
        for field, invalid in [('discovery_max_resolution', 1440),
                               ('discovery_max_resolution', True),
                               ('discovery_min_seeders', -1),
                               ('discovery_rank_by', 'custom_formats')]:
            with self.subTest(field=field), self.assertRaises(ConfigurationError):
                ConfigurationSnapshot(1, {'sonarr': {field: invalid}})


    def test_saved_release_json_summary_is_read_only_and_masks_source_urls(self):
        from src.nextgen.acquisition.validate_sonarr_json import summarize
        magnet = 'magnet:?xt=urn:btih:' + HASH
        rows = [
            release(title='Profile rejected but candidate valid', guid=magnet,
                    magnetUrl='', approved=False, rejected=True,
                    rejections=['Quality profile restriction'], seeders=20),
            release(title='No peers', guid=magnet, magnetUrl='', seeders=0),
            release(title='Wrong episode', guid=magnet, magnetUrl='',
                    mappedEpisodeInfo=[{'id': 99, 'seasonNumber': 1, 'episodeNumber': 9}]),
        ]
        summary = summarize(rows, ID, sonarr_series=11, sonarr_episode=22,
                            policy=DiscoveryPolicy())
        self.assertEqual(summary['total'], 3)
        self.assertEqual(summary['magnet_sources'], 3)
        self.assertEqual(summary['local_eligible'], 1)
        self.assertEqual(summary['scope']['mismatched'], 1)
        self.assertFalse(summary['top_eligible'][0]['sonarr_approved'])
        self.assertNotIn('magnet:', repr(summary))

    def test_does_not_leak_secret_or_magnet_via_repr(self):
        c, _ = client()
        row = c.search(ID).candidates[0]
        self.assertNotIn('private-sonarr-key', repr(c))
        self.assertNotIn('magnet:', repr(row))

    def test_authenticated_configuration_from_existing_settings(self):
        class Configuration:
            def value(self, field):
                return {'sonarr.base_url': 'http://sonarr.invalid',
                        'sonarr.timeout_seconds': 13,
                        'sonarr.discovery_max_resolution': 1080,
                        'sonarr.discovery_min_seeders': 5,
                        'sonarr.discovery_rank_by': 'resolution'}[field]
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

    def test_empty_episode_catalog_does_not_search_or_write_to_sonarr(self):
        c, fake = client()
        fake.episodes = []
        observations = c.backfill(100, 2, (5,6), reserved=(5,))
        self.assertEqual([o.status for o in observations], ['IN_PROGRESS','NOT_LISTED'])
        self.assertEqual([urlsplit(u).path for u in fake.visited],
                         ['/api/v3/system/status','/api/v3/series','/api/v3/episode'])

    def test_request_logs_show_work_without_credentials_or_magnets(self):
        import logging
        c, fake = client()
        c.logger = logging.getLogger('sonarr-discovery-test')
        with self.assertLogs(c.logger, level='INFO') as logs:
            c.search(ID)
        messages = '\n'.join(logs.output)
        self.assertIn('endpoint=release', messages)
        self.assertIn('timeout_seconds=180', messages)
        self.assertIn('elapsed_seconds=', messages)
        self.assertNotIn('private-sonarr-key', messages)
        self.assertNotIn('magnet:', messages)

    def test_release_timeout_is_distinct_and_does_not_repeat_request(self):
        from src.nextgen.acquisition.sonarr_search import SearchTimeout
        for error in (TimeoutError(), urllib.error.URLError(TimeoutError())):
            c, fake = client()
            def transport(request, timeout):
                if urlsplit(request.full_url).path == '/api/v3/release':
                    fake.visited.append(request.full_url)
                    self.assertEqual(timeout, 180)
                    raise error
                return fake(request, timeout)
            c._transport = transport
            with self.subTest(error=type(error)), self.assertRaises(SearchTimeout):
                c.search(ID)
            self.assertEqual(len(fake.visited), 4)

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

    def test_backfill_queries_only_missing_listed_unreserved_episode(self):
        c, fake = client()
        fake.episodes.extend([
            {'id': 23, 'seriesId': 11, 'tvdbId': 201, 'seasonNumber': 1,
             'episodeNumber': 11, 'hasFile': False},
            {'id': 24, 'seriesId': 11, 'tvdbId': 202, 'seasonNumber': 1,
             'episodeNumber': 12, 'hasFile': True},
        ])
        fake.episodes[0]['hasFile'] = False
        obs = c.backfill(100, 1, (10,11,12,13),
                         reserved=(11,), verified_ids={10: 200})
        self.assertEqual([o.status for o in obs],
                         ['CANDIDATES','IN_PROGRESS','HAS_FILE','NOT_LISTED'])
        self.assertEqual((obs[0].candidates,obs[0].approved,obs[0].exact),(1,1,1))
        self.assertEqual([urlsplit(v).path for v in fake.visited].count('/api/v3/release'),1)

    def test_backfill_conflicting_verified_episode_never_queries_indexers(self):
        c, fake = client()
        fake.episodes[0]['hasFile'] = False
        obs = c.backfill(100, 1, (10,), verified_ids={10:999})
        self.assertEqual(obs[0].status,'IDENTITY_CONFLICT')
        self.assertNotIn('/api/v3/release',[urlsplit(u).path for u in fake.visited])

    def test_backfill_missing_or_unsafe_sonarr_episode_id_never_queries(self):
        c, fake = client()
        fake.episodes[0]['hasFile'] = False
        fake.episodes[0]['tvdbId'] = 0
        self.assertEqual(c.backfill(100,1,(10,))[0].status,'IDENTITY_UNKNOWN')
        self.assertNotIn('/api/v3/release',[urlsplit(u).path for u in fake.visited])
