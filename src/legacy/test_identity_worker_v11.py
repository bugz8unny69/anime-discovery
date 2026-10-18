import json
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch
from anime_http_guard_v11 import Guard, RateLimited, retry_after_seconds, protected

class TestGuard(unittest.TestCase):
    def test_retry_after(self):
        self.assertEqual(retry_after_seconds('12'), 12)
        self.assertIsNone(retry_after_seconds('bad'))
    def test_persistent_spacing(self):
        with tempfile.TemporaryDirectory() as d:
            clock = [100.0]
            waits = []
            def sleep(n):
                waits.append(n)
                clock[0] += n
            g = Guard(Path(d)/'rate.json', 2, sleeper=sleep, clock=lambda: clock[0])
            g.open(lambda *a, **k: 'ok', 'https://api4.thetvdb.com/v4/search')
            g2 = Guard(Path(d)/'rate.json', 2, sleeper=sleep, clock=lambda: clock[0])
            g2.open(lambda *a, **k: 'ok', 'https://api4.thetvdb.com/v4/login')
            self.assertEqual(waits, [2.0])
            self.assertEqual(g2.count, 1)
    def test_disallowed_host(self):
        with tempfile.TemporaryDirectory() as d:
            g = Guard(Path(d)/'rate.json')
            with self.assertRaises(ValueError):
                g.open(lambda *a, **k: None, 'https://example.com/')
    def test_429_defers(self):
        with tempfile.TemporaryDirectory() as d:
            g = Guard(Path(d)/'rate.json', sleeper=lambda _: None, clock=lambda: 100)
            err = urllib.error.HTTPError('https://api4.thetvdb.com', 429, 'rate', {'Retry-After': '60'}, None)
            with self.assertRaises(RateLimited):
                g.open(lambda *a, **k: (_ for _ in ()).throw(err), 'https://api4.thetvdb.com/v4/search')
            self.assertGreaterEqual(json.loads((Path(d)/'rate.json').read_text())['next_at'], 160)
    def test_patch_restored(self):
        original = urllib.request.urlopen
        with tempfile.TemporaryDirectory() as d:
            with protected(Path(d)/'rate.json'):
                self.assertIsNot(urllib.request.urlopen, original)
        self.assertIs(urllib.request.urlopen, original)

if __name__ == '__main__': unittest.main()
