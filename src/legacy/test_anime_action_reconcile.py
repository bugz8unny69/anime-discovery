import sqlite3
import unittest
from anime_external_actions import reserve, transition
from anime_action_reconcile import reconcile

class ReconcileTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)

    def test_confirm_after_read_only_lookup(self):
        token=reserve(self.db,"torrent","hash123","fingerprint")
        transition(self.db,"torrent","hash123",token,"RESERVED","UNCERTAIN")
        calls=[]
        def lookup(kind,key):
            calls.append((kind,key))
            return "hash123"
        self.assertEqual(reconcile(self.db,"torrent","hash123","fingerprint",lookup),"hash123")
        self.assertEqual(reconcile(self.db,"torrent","hash123","fingerprint",lookup),"hash123")
        self.assertEqual(len(calls),1)

    def test_unconfirmed_does_not_resubmit(self):
        token=reserve(self.db,"torrent","hash123","fingerprint")
        transition(self.db,"torrent","hash123",token,"RESERVED","UNCERTAIN")
        self.assertIsNone(reconcile(self.db,"torrent","hash123","fingerprint",lambda a,b:None))
        self.assertIsNone(reserve(self.db,"torrent","hash123","fingerprint"))

if __name__=="__main__":
    unittest.main()
