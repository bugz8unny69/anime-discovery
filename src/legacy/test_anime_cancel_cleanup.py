"""Isolated canceled-torrent cleanup fencing tests, no live qB or media."""
import sqlite3
import unittest
from anime_async_daemon import enqueue
from anime_job_management import manage
from anime_cancel_cleanup import prepare,cleanup_torrents

H="a"*40
class MockQB:
    def __init__(self):
        self.record={"hash":H,"category":"anime-discovery","tags":"ad-proven"}
        self.removed=[]
        self.fail=False
    def torrent_identity(self,h):
        return self.record
    def remove_torrent(self,h,*,delete_files):
        assert delete_files is False
        self.removed.append(h)
        self.record=None
        if self.fail: raise OSError("Simulated lost acknowledgement")

class CancelCleanupTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:",isolation_level=None)
        self.addCleanup(self.db.close)
        enqueue(self.db,"claimed_acquisition","7",'{"notification_id":7}')
        self.jid=self.db.execute("SELECT id FROM daemon_jobs").fetchone()[0]
        self.db.execute("""CREATE TABLE torrent_recovery_records
            (notification_id INTEGER, infohash TEXT)""")
        self.db.execute("""CREATE TABLE anime_batch_authorizations
            (notification_id INTEGER, infohash TEXT)""")
        self.db.execute("""CREATE TABLE qb_torrent_ownership
            (infohash TEXT,status TEXT,marker TEXT,category TEXT)""")
        self.db.execute("INSERT INTO torrent_recovery_records VALUES (7,?)",(H,))
        self.db.execute("""INSERT INTO qb_torrent_ownership VALUES
            (?,'OWNED','ad-proven','anime-discovery')""",(H,))
        self.db.execute("UPDATE daemon_jobs SET state='NEEDS_REVIEW'")
        manage(self.db,self.jid,"cancel",expected_state="NEEDS_REVIEW",expected_attempts=0)
        self.qb=MockQB()

    def test_requires_approval_and_exact_marker(self):
        self.assertTrue(prepare(self.db,self.jid)["can_remove_torrents"])
        with self.assertRaises(PermissionError):
            cleanup_torrents(self.db,self.jid,self.qb)
        self.assertEqual(self.qb.removed,[])
        self.qb.record["tags"]="other"
        with self.assertRaises(ValueError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(self.qb.removed,[])

    def test_shared_hash_refuses_removal(self):
        self.db.execute("INSERT INTO torrent_recovery_records VALUES (9,?)",(H,))
        self.assertFalse(prepare(self.db,self.jid)["can_remove_torrents"])
        with self.assertRaises(ValueError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(self.qb.removed,[])

    def test_owned_torrent_only_never_deletes_files_and_idempotent(self):
        self.assertEqual(cleanup_torrents(self.db,self.jid,self.qb,approved=True),[(H,"REMOVED")])
        self.assertEqual(self.qb.removed,[H])
        self.assertEqual(cleanup_torrents(self.db,self.jid,self.qb,approved=True),[(H,"REMOVED")])
        self.assertEqual(self.qb.removed,[H])

    def test_timeout_requires_manual_review(self):
        self.qb.fail=True
        with self.assertRaises(OSError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_job_cleanup_attempts").fetchone()[0],"UNCERTAIN")
        with self.assertRaisesRegex(ValueError,"uncertain"):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(len(self.qb.removed),1)

    def test_unproven_status_blocks(self):
        self.db.execute("UPDATE qb_torrent_ownership SET status='UNCERTAIN'")
        self.assertFalse(prepare(self.db,self.jid)["can_remove_torrents"])
        with self.assertRaises(ValueError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)

if __name__=="__main__":
    unittest.main()
