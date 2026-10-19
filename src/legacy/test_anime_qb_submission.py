"""Offline qBittorrent submission tests; no live client required."""
import sqlite3
import unittest
from anime_qb_submission import submit_once

HASH="a"*40
MAGNET="magnet:?xt=urn:btih:"+HASH

class FakeQB:
    def __init__(self):
        self.hashes=set()
        self.calls=0
    def contains_hash(self, value):
        return value in self.hashes
    def add_magnet(self, uri):
        self.calls+=1
        self.hashes.add(HASH)

class SubmissionTests(unittest.TestCase):
    def test_submit_and_deduplicate(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,1)

    def test_wrong_magnet_is_rejected(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            with self.assertRaises(ValueError):
                submit_once(db,HASH,"magnet:?xt=urn:btih:"+"b"*40,FakeQB())

if __name__=="__main__":
    unittest.main()
