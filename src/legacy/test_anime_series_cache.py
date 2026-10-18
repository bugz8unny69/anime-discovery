import sqlite3
import unittest
from anime_series_cache import ensure_schema,cached_mapping,store_verified,torrent_submission_options

class CacheTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        ensure_schema(self.db)
        self.mapping=dict(source="tvdb",external_id="123",anidb_id="456",tvdb_id="123",
                          ordering_json='{"offset":0}',evidence_hash="verified")

    def test_reuse_without_remote_lookup(self):
        store_verified(self.db,**self.mapping)
        self.assertEqual(cached_mapping(self.db,"tvdb","123")["tvdb_id"],"123")
        store_verified(self.db,**self.mapping)
        self.assertEqual(self.db.execute("SELECT count(*) FROM verified_series_cache").fetchone()[0],1)

    def test_conflicting_identity_refused(self):
        store_verified(self.db,**self.mapping)
        changed=dict(self.mapping,anidb_id="999")
        with self.assertRaises(ValueError):
            store_verified(self.db,**changed)

    def test_no_qbittorrent_queue_override(self):
        self.assertEqual(torrent_submission_options(),{})
        with self.assertRaises(ValueError):
            torrent_submission_options(priority_mode="force_high")

if __name__=="__main__":
    unittest.main()
