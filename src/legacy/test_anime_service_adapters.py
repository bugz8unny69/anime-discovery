import json
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from urllib.error import HTTPError

from anime_service_adapters import QBittorrentReadOnly, SonarrReadOnly, AdapterError

HASH = 'a' * 40

class Handler(BaseHTTPRequestHandler):
    requests = []
    def log_message(self, *args):
        pass
    def do_POST(self):
        self.requests.append((self.command, self.path, self.headers.get('Origin')))
        if self.path != '/api/v2/auth/login':
            self.send_error(404); return
        length = int(self.headers.get('Content-Length', '0'))
        body = self.rfile.read(length).decode()
        if 'username=demo' not in body or 'password=secret' not in body:
            self.send_error(403); return
        self.send_response(200)
        self.send_header('Set-Cookie', 'SID=mock-session; HttpOnly; path=/')
        self.end_headers()
        self.wfile.write(b'Ok.')
    def do_GET(self):
        self.requests.append((self.command, self.path, self.headers.get('Cookie')))
        if self.headers.get('Cookie') != 'SID=mock-session':
            self.send_error(403); return
        if self.path == '/api/v2/app/version':
            data = b'4.5.2'
        elif self.path == '/api/v2/torrents/info':
            data = json.dumps([{'hash': HASH, 'name':'test', 'state':'downloading', 'save_path':'/tmp/staging', 'progress':0.5}]).encode()
        else:
            self.send_error(404); return
        self.send_response(200); self.end_headers(); self.wfile.write(data)

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.url = 'http://127.0.0.1:{}'.format(cls.server.server_port)
    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown(); cls.server.server_close(); cls.thread.join()
    def setUp(self):
        Handler.requests.clear()
    def test_login_and_version(self):
        q = QBittorrentReadOnly(self.url, 'demo', 'secret'); q.login()
        self.assertEqual(q.version(), '4.5.2')
        self.assertEqual([r[0] for r in Handler.requests], ['POST', 'GET'])
    def test_inventory(self):
        q = QBittorrentReadOnly(self.url, 'demo', 'secret'); q.login()
        torrents = q.torrents()
        self.assertEqual(torrents[0].torrent_hash, HASH)
        self.assertEqual(torrents[0].progress, .5)
    def test_requires_login(self):
        with self.assertRaises(AdapterError):
            QBittorrentReadOnly(self.url, 'demo', 'secret').torrents()
    def test_bad_password(self):
        with self.assertRaises(AdapterError):
            QBittorrentReadOnly(self.url, 'demo', 'wrong').login()
    def test_local_http_only(self):
        with self.assertRaises(ValueError):
            QBittorrentReadOnly('https://example.com', 'a', 'b')
    def test_reject_credentials_in_url(self):
        with self.assertRaises(ValueError):
            QBittorrentReadOnly('http://u:p@127.0.0.1:8080', 'a', 'b')
    def test_reject_path(self):
        with self.assertRaises(ValueError):
            QBittorrentReadOnly(self.url + '/foo', 'a', 'b')
    def test_no_mutation_method(self):
        q = QBittorrentReadOnly(self.url, 'demo', 'secret')
        self.assertFalse(hasattr(q, 'delete'))
        self.assertFalse(hasattr(q, 'cancel'))
    def test_sonarr_https_only(self):
        with self.assertRaises(ValueError):
            SonarrReadOnly('http://sonarr.arr.internal', 'test')
    def test_sonarr_key_required(self):
        with self.assertRaises(ValueError):
            SonarrReadOnly('https://sonarr.arr.internal', '')
    def test_sonarr_positive_id(self):
        s = SonarrReadOnly('https://sonarr.arr.internal', 'test')
        with self.assertRaises(ValueError):
            s.episodes(0)
    def test_sonarr_get_only(self):
        s = SonarrReadOnly('https://sonarr.arr.internal', 'test')
        self.assertFalse(hasattr(s, 'post'))
        self.assertFalse(hasattr(s, 'handoff'))
    def test_sonarr_auth_header_and_status(self):
        s = SonarrReadOnly('https://sonarr.arr.internal', 'fake-key')
        captured = []
        class FakeResponse:
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self): return b'{"version":"4.0.0", "appName":"Sonarr"}'
        def fake_open(req, timeout):
            captured.append(req)
            return FakeResponse()
        with patch.object(s._opener, 'open', side_effect=fake_open):
            self.assertEqual(s.status()['version'], '4.0.0')
        self.assertEqual(captured[0].get_header('X-api-key'), 'fake-key')
        self.assertEqual(captured[0].get_method(), 'GET')
    def test_sonarr_episodes(self):
        s = SonarrReadOnly('https://sonarr.arr.internal', 'fake-key')
        with patch.object(s, '_get', return_value=[{'seasonNumber':1,'episodeNumber':1}]) as get:
            self.assertEqual(s.episodes(3)[0]['episodeNumber'], 1)
            get.assert_called_once_with('/api/v3/episode?seriesId=3')
    def test_sonarr_series(self):
        s = SonarrReadOnly('https://sonarr.arr.internal', 'fake-key')
        with patch.object(s, '_get', return_value=[]) as get:
            self.assertEqual(s.series(), [])
            get.assert_called_once_with('/api/v3/series')

if __name__ == '__main__': unittest.main()
