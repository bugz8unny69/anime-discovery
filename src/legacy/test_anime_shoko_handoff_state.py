import sqlite3
import unittest
from anime_shoko_handoff_state import (enqueue_verified_copies,
    record_verified_episode, reconcile_one)

class StateTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        self.manifest=[{"notification_id":17}]
        enqueue_verified_copies(self.db,4,self.manifest,["/mnt/media/Anime/example.mkv"])
    def test_requires_provenance(self):
        with self.assertRaises(ValueError):
            record_verified_episode(self.db,series_id=4,notification_id=999,
                                    anidb_episode_id=33)
    def test_no_guessing(self):
        def observe(url,key,**kwargs):
            self.assertIsNone(kwargs["anidb_episode_id"])
            self.assertFalse(kwargs["verified_episode_identity"])
            return {"status":"NEEDS_EPISODE_IDENTITY","writes_enabled":False}
        result=reconcile_one(self.db,{"shoko":{"base_url":"https://host"},
            "sonarr":{"root_folder":"/mnt/media/Anime"}},
            {"shoko_api_key":"test"},series_id=4,notification_id=17,inspector=observe)
        self.assertEqual(result["status"],"NEEDS_EPISODE_IDENTITY")
    def test_explicit_identity_enables_read_only_retry(self):
        record_verified_episode(self.db,series_id=4,notification_id=17,anidb_episode_id=33)
        def observe(url,key,**kwargs):
            self.assertEqual(kwargs["anidb_episode_id"],33)
            self.assertTrue(kwargs["verified_episode_identity"])
            return {"status":"LINK_PLAN_READY","writes_enabled":False}
        for _ in range(2):
            reconcile_one(self.db,{"shoko":{"base_url":"https://host"},
                "sonarr":{"root_folder":"/mnt/media/Anime"}},
                {"shoko_api_key":"test"},series_id=4,notification_id=17,
                inspector=observe)
    def test_changed_destination_blocks(self):
        with self.assertRaises(RuntimeError):
            enqueue_verified_copies(self.db,4,self.manifest,["/another.mkv"])
    def test_inspector_cannot_authorize_write(self):
        def bad(*args,**kwargs):
            return {"status":"LINK_PLAN_READY","writes_enabled":True}
        with self.assertRaises(RuntimeError):
            reconcile_one(self.db,{"shoko":{"base_url":"https://host"},
                "sonarr":{"root_folder":"/mnt/media/Anime"}},
                {"shoko_api_key":"test"},series_id=4,notification_id=17,
                inspector=bad)

if __name__=="__main__":unittest.main()
