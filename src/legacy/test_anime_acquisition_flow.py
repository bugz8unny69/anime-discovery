import sqlite3
import unittest
from unittest.mock import patch
from anime_acquisition_flow import acquire_claimed

HASH="a"*40
MAGNET="magnet:?xt=urn:btih:"+HASH

class FakeQB:
    def __init__(self):
        self.present=set()
        self.calls=0
    def contains_hash(self,key):
        return key in self.present
    def add_magnet(self,uri):
        self.calls+=1
        self.present.add(HASH)

class FlowTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        self.db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY,info_hash TEXT)")
        self.db.execute("INSERT INTO notifications VALUES(7,?)",(HASH,))

    @patch("anime_acquisition_flow.approved_dispatch")
    def test_verified_submission_is_idempotent(self,gate):
        qb=FakeQB()
        self.assertEqual(acquire_claimed(self.db,7,HASH,MAGNET,qb),HASH)
        self.assertEqual(acquire_claimed(self.db,7,HASH,MAGNET,qb),HASH)
        self.assertEqual(qb.calls,1)
        self.assertEqual(gate.call_count,2)

    @patch("anime_acquisition_flow.approved_dispatch")
    def test_wrong_notification_hash_never_submits(self,gate):
        qb=FakeQB()
        with self.assertRaises(ValueError):
            acquire_claimed(self.db,7,"b"*40,MAGNET,qb)
        self.assertEqual(qb.calls,0)

    @patch("anime_acquisition_flow.approved_dispatch",side_effect=ValueError("Rejected"))
    def test_rejection_never_submits(self,gate):
        qb=FakeQB()
        with self.assertRaises(ValueError):
            acquire_claimed(self.db,7,HASH,MAGNET,qb)
        self.assertEqual(qb.calls,0)

if __name__=="__main__":
    unittest.main()
