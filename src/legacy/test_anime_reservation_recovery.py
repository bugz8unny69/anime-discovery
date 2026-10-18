import sqlite3
import unittest
from unittest.mock import patch
from anime_external_actions import reserve
from anime_qb_submission import submit_once

class FakeQB:
    def __init__(self, present=False):
        self.present=present
        self.added=0
    def contains_hash(self, key):
        return self.present
    def add_magnet(self, magnet):
        self.added+=1
        self.present=True

class ReservationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        self.infohash='a'*40
        self.magnet='magnet:?xt=urn:btih:'+self.infohash
    def tearDown(self):
        self.db.close()
    def test_reserved_missing_does_not_resubmit(self):
        import hashlib
        reserve(self.db,'qbittorrent_submit',self.infohash,
                hashlib.sha256(self.magnet.encode()).hexdigest())
        qb=FakeQB()
        self.assertIsNone(submit_once(self.db,self.infohash,self.magnet,qb))
        self.assertEqual(qb.added,0)
        self.assertEqual(self.db.execute('SELECT state FROM external_actions').fetchone()[0],'UNCERTAIN')
    def test_reserved_present_is_reconciled(self):
        import hashlib
        reserve(self.db,'qbittorrent_submit',self.infohash,
                hashlib.sha256(self.magnet.encode()).hexdigest())
        qb=FakeQB(True)
        self.assertEqual(submit_once(self.db,self.infohash,self.magnet,qb),self.infohash)
        self.assertEqual(qb.added,0)
        self.assertEqual(self.db.execute('SELECT state FROM external_actions').fetchone()[0],'CONFIRMED')

if __name__=='__main__':
    unittest.main()
