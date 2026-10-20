"""Offline qBittorrent ownership and idempotent submission tests."""
import sqlite3
import unittest
from anime_qb_submission import submit_once
from anime_qb_ownership import CATEGORY,OWNED,EXTERNAL,UNCERTAIN,ownership

HASH="a"*40
MAGNET="magnet:?xt=urn:btih:"+HASH

class FakeQB:
    def __init__(self):
        self.records={}
        self.calls=0
        self.identity_visible=True
    def contains_hash(self,value):
        return value in self.records
    def torrent_identity(self,value):
        return self.records.get(value) if self.identity_visible else None
    def add_magnet(self,uri,*,category,tag):
        self.calls+=1
        self.records[HASH]={"hash":HASH,"category":category,"tags":tag}

class SubmissionTests(unittest.TestCase):
    def test_submit_category_marker_and_deduplicate(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(ownership(db,HASH),OWNED)
            self.assertEqual(qb.records[HASH]["category"],CATEGORY)
            self.assertTrue(qb.records[HASH]["tags"].startswith("ad-"))
            self.assertEqual(db.execute("SELECT marker FROM qb_torrent_ownership").fetchone()[0],
                             qb.records[HASH]["tags"])
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,1)

    def test_new_owned_torrent_receives_explicit_save_path(self):
        class PathQB(FakeQB):
            def add_magnet(self,uri,*,category,tag,save_path=None):
                self.submitted_path=save_path
                super().add_magnet(uri,category=category,tag=tag)
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=PathQB()
            submit_once(db,HASH,MAGNET,qb,save_path="/mnt/media/Torrents/anime")
            self.assertEqual(qb.submitted_path,"/mnt/media/Torrents/anime")
            self.assertEqual(ownership(db,HASH),OWNED)
            submit_once(db,HASH,MAGNET,qb,save_path="/mnt/media/Torrents/anime")
            self.assertEqual(qb.calls,1)

    def test_preexisting_exact_hash_is_external_and_never_added(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            qb.records[HASH]={"hash":HASH,"category":"movies","tags":""}
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,0)
            self.assertEqual(ownership(db,HASH),EXTERNAL)
            self.assertEqual(qb.records[HASH]["category"],"movies")

    def test_retry_rearms_after_preexisting_external_torrent_removed(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            qb.records[HASH]={"hash":HASH,"category":"other","tags":""}
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(ownership(db,HASH),EXTERNAL)
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,0)
            qb.records.pop(HASH)
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,1)
            self.assertEqual(ownership(db,HASH),OWNED)
            self.assertTrue(qb.records[HASH]["tags"].startswith("ad-"))
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,1)

    def test_uncertain_missing_torrent_never_resubmitted(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            qb.identity_visible=False
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            qb.records.clear()
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(qb.calls,1)
            self.assertEqual(ownership(db,HASH),UNCERTAIN)

    def test_missing_post_add_marker_is_not_owned(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            qb.identity_visible=False
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(ownership(db,HASH),UNCERTAIN)
            self.assertEqual(qb.calls,1)
            qb.identity_visible=True
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(ownership(db,HASH),OWNED)
            self.assertEqual(qb.calls,1)

    def test_other_app_category_cannot_prove_ownership(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            qb=FakeQB()
            qb.identity_visible=False
            submit_once(db,HASH,MAGNET,qb)
            qb.identity_visible=True
            qb.records[HASH]["category"]="other-app"
            submit_once(db,HASH,MAGNET,qb)
            self.assertEqual(ownership(db,HASH),UNCERTAIN)

    def test_legacy_confirmed_submission_has_no_delete_authorization(self):
        from anime_external_actions import reserve,transition
        import hashlib
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            fingerprint=hashlib.sha256(MAGNET.encode()).hexdigest()
            token=reserve(db,"qbittorrent_submit",HASH,fingerprint)
            transition(db,"qbittorrent_submit",HASH,token,"RESERVED","UNCERTAIN")
            qb=FakeQB()
            qb.records[HASH]={"hash":HASH,"category":CATEGORY,"tags":""}
            self.assertEqual(submit_once(db,HASH,MAGNET,qb),HASH)
            self.assertEqual(ownership(db,HASH),UNCERTAIN)
            self.assertEqual(qb.calls,0)

    def test_wrong_magnet_is_rejected(self):
        with sqlite3.connect(":memory:",isolation_level=None) as db:
            with self.assertRaises(ValueError):
                submit_once(db,HASH,"magnet:?xt=urn:btih:"+"b"*40,FakeQB())

if __name__=="__main__":
    unittest.main()
