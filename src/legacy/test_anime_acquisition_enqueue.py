import json
import sqlite3
import unittest
from unittest.mock import patch
from anime_acquisition_enqueue import enqueue_claimed_acquisition

class EnqueueTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.db.execute("CREATE TABLE notifications(id INTEGER,info_hash TEXT)")
        self.db.execute("CREATE TABLE verified_series_identity(notification_id INTEGER,tvdb_id TEXT)")
        self.db.execute("INSERT INTO notifications VALUES(7,?)",("a"*40,))
        self.db.execute("INSERT INTO verified_series_identity VALUES(7,'123')")
    def tearDown(self):
        self.db.close()
    def test_enqueue_is_idempotent(self):
        with patch("anime_acquisition_enqueue.approved_dispatch",return_value={}):
            kw={"infohash":"a"*40,"magnet_uri":"magnet:?xt=urn:btih:"+"a"*40,
                "title":"Example","tvdb_id":123}
            self.assertTrue(enqueue_claimed_acquisition(self.db,7,**kw))
            self.assertFalse(enqueue_claimed_acquisition(self.db,7,**kw))
            self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs").fetchone()[0],1)
    def test_mismatched_hash_is_rejected(self):
        with patch("anime_acquisition_enqueue.approved_dispatch",return_value={}):
            with self.assertRaisesRegex(ValueError,"identity"):
                enqueue_claimed_acquisition(self.db,7,infohash="b"*40,
                    magnet_uri="magnet:?xt=urn:btih:"+"b"*40,
                    title="Example",tvdb_id=123)

if __name__=="__main__":
    unittest.main()
