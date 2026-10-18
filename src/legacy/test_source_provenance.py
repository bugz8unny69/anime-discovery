import json
import unittest
from datetime import datetime, timezone
from urllib.parse import urlsplit
from source_provenance import SonarrConfig, SourceError, fetch_sonarr_catalog, capture_identity_evidence

ANI = {'data': {'Media': {'id': 11061, 'idMal': 11061, 'title': {'english': 'Hunter x Hunter'}, 'episodes': 148, 'format': 'TV', 'isAdult': False}}}
SERIES = {'id': 5, 'title': 'Hunter x Hunter'}
EPS = [{'id': 50, 'seriesId': 5, 'seasonNumber': 1, 'episodeNumber': 1, 'absoluteEpisodeNumber': 1},
       {'id': 51, 'seriesId': 5, 'seasonNumber': 0, 'episodeNumber': 1, 'absoluteEpisodeNumber': None}]

def wire(ani=None, series=None, episodes=None):
    def transport(req):
        path = urlsplit(req.full_url).path
        if 'graphql.anilist.co' in req.full_url:
            data = ANI if ani is None else ani
        elif path.endswith('/series/5'):
            data = SERIES if series is None else series
        elif path.endswith('/episode'):
            data = EPS if episodes is None else episodes
        else:
            raise AssertionError(req.full_url)
        return json.dumps(data).encode()
    return transport

class Tests(unittest.TestCase):
    def setUp(self):
        self.cfg = SonarrConfig('http://127.0.0.1:8989', 'secret-long-enough')
    def test_good_catalog(self):
        c = fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire())
        self.assertEqual(c['episodes'][0]['absolute'], 1)
        self.assertFalse(c['canonical_mapping_authorized'])
    def test_capture(self):
        c = capture_identity_evidence(anilist_id=11061, sonarr_config=self.cfg, sonarr_series_id=5, transport=wire(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(len(c['sha256']), 64)
        self.assertEqual(c['captured_at'], 1767225600)
        self.assertFalse(c['canonical_mapping_authorized'])
    def test_repeatable_hash(self):
        kw = dict(anilist_id=11061, sonarr_config=self.cfg, sonarr_series_id=5, transport=wire(), clock=lambda: datetime(2026, 1, 1, tzinfo=timezone.utc))
        self.assertEqual(capture_identity_evidence(**kw)['sha256'], capture_identity_evidence(**kw)['sha256'])
    def test_http_remote_rejected(self):
        with self.assertRaises(SourceError): SonarrConfig('http://192.168.1.2:8989', 'secret-long-enough')
    def test_https_remote_allowed(self):
        SonarrConfig('https://sonarr.example.org', 'secret-long-enough')
    def test_url_credentials_rejected(self):
        with self.assertRaises(SourceError): SonarrConfig('https://u:p@sonarr.example.org', 'secret-long-enough')
    def test_url_path_rejected(self):
        with self.assertRaises(SourceError): SonarrConfig('https://sonarr.example.org/proxy', 'secret-long-enough')
    def test_short_key_rejected(self):
        with self.assertRaises(SourceError): SonarrConfig('https://sonarr.example.org', 'short')
    def test_wrong_series(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(series={'id': 6, 'title': 'x'}))
    def test_empty_catalog(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(episodes=[]))
    def test_wrong_episode_owner(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(episodes=[dict(EPS[0], seriesId=6)]))
    def test_duplicate_episode_id(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(episodes=[EPS[0], EPS[0]]))
    def test_boolean_episode_id(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(episodes=[dict(EPS[0], id=True)]))
    def test_negative_absolute(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(episodes=[dict(EPS[0], absoluteEpisodeNumber=-1)]))
    def test_bad_season(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire(episodes=[dict(EPS[0], seasonNumber='1')]))
    def test_bad_anilist_id(self):
        with self.assertRaises(SourceError): capture_identity_evidence(anilist_id=True, sonarr_config=self.cfg, sonarr_series_id=5, transport=wire())
    def test_wrong_anilist_response(self):
        with self.assertRaises(SourceError): capture_identity_evidence(anilist_id=11061, sonarr_config=self.cfg, sonarr_series_id=5, transport=wire(ani={'data': {'Media': dict(ANI['data']['Media'], id=3)}}))
    def test_naive_clock(self):
        with self.assertRaises(SourceError): capture_identity_evidence(anilist_id=11061, sonarr_config=self.cfg, sonarr_series_id=5, transport=wire(), clock=lambda: datetime(2026, 1, 1))
    def test_malformed_json(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=lambda req: b'bad json')
    def test_large_response(self):
        with self.assertRaises(SourceError): fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=lambda req: b'x'*2_000_001)
    def test_no_secret_in_result(self):
        c = fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=wire())
        self.assertNotIn(self.cfg.api_key, repr(c))
    def test_api_key_header(self):
        def check(req):
            self.assertEqual(req.get_header('X-api-key'), self.cfg.api_key)
            return wire()(req)
        fetch_sonarr_catalog(self.cfg, sonarr_series_id=5, transport=check)

if __name__ == '__main__': unittest.main(verbosity=2)
