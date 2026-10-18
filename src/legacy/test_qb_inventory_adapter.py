import io
import json
import unittest
from qb_inventory_adapter import (InventoryError, parse_inventory, fetch_inventory,
                                  validate_base_url, preflight)
H = 'a' * 40
J = 'b' * 40

def record(h=H, state='downloading', name='Episode 1'):
    return {'hash': h, 'state': state, 'name': name}

class Response(io.BytesIO):
    def getcode(self): return 200

class Tests(unittest.TestCase):
    def test_valid_inventory(self):
        self.assertEqual(parse_inventory(json.dumps([record()]).encode())[0].torrent_hash, H)
    def test_empty_inventory(self):
        self.assertEqual(parse_inventory(b'[]'), ())
    def test_duplicate_hash(self):
        with self.assertRaises(InventoryError): parse_inventory([record(), record(H.upper())])
    def test_invalid_hash(self):
        with self.assertRaises(InventoryError): parse_inventory([record('bad')])
    def test_invalid_state(self):
        with self.assertRaises(InventoryError): parse_inventory([record(state='invented')])
    def test_invalid_name(self):
        with self.assertRaises(InventoryError): parse_inventory([record(name=None)])
    def test_bad_json(self):
        with self.assertRaises(InventoryError): parse_inventory(b'not json')
    def test_oversized_response(self):
        with self.assertRaises(InventoryError): parse_inventory(b' ' * 4_000_001)
    def test_non_list(self):
        with self.assertRaises(InventoryError): parse_inventory(b'{}')
    def test_loopback_http(self):
        self.assertEqual(validate_base_url('http://127.0.0.1:8080'), 'http://127.0.0.1:8080')
    def test_remote_http_rejected(self):
        for u in ('http://192.168.1.10:8080', 'http://localhost:8080', 'http://example.com'):
            with self.subTest(u=u), self.assertRaises(InventoryError): validate_base_url(u)
    def test_remote_https(self):
        self.assertEqual(validate_base_url('https://qb.example.org'), 'https://qb.example.org')
    def test_credentials_in_url_rejected(self):
        with self.assertRaises(InventoryError): validate_base_url('https://user:pass@qb.example.org')
    def test_fetch_get_only(self):
        def transport(req):
            self.assertEqual(req.get_method(), 'GET')
            self.assertTrue(req.full_url.endswith('/api/v2/torrents/info'))
            self.assertEqual(req.get_header('Cookie'), 'SID=abcdefgh')
            return Response(json.dumps([record()]).encode())
        self.assertEqual(len(fetch_inventory('https://qb.example.org', 'abcdefgh', transport=transport)), 1)
    def test_bad_sid(self):
        with self.assertRaises(InventoryError): fetch_inventory('https://qb.example.org', 'x;evil')
    def test_preflight_matching(self):
        p = preflight(7, H, parse_inventory([record()]), current_attempt_id=7)
        self.assertEqual(p.outcome, 'WOULD_REMOVE_TORRENT_ONLY')
        self.assertTrue(p.dry_run)
    def test_preflight_missing(self):
        self.assertEqual(preflight(7, H, (), current_attempt_id=7).outcome, 'ALREADY_ABSENT')
    def test_preflight_stale(self):
        self.assertEqual(preflight(7, H, parse_inventory([record()]), current_attempt_id=8).outcome, 'BLOCKED')
    def test_preflight_other_hash(self):
        self.assertEqual(preflight(7, J, parse_inventory([record()]), current_attempt_id=7).outcome, 'ALREADY_ABSENT')
    def test_preflight_bad_attempt(self):
        with self.assertRaises(InventoryError): preflight(True, H, ())
    def test_preflight_bad_inventory(self):
        with self.assertRaises(InventoryError): preflight(7, H, [record()])

if __name__ == '__main__':
    unittest.main(verbosity=2)
