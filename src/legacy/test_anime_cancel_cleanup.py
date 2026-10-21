"""Isolated canceled-torrent cleanup fencing tests, no live qB or media."""
import sqlite3
import tempfile
from pathlib import Path
import unittest
from anime_async_daemon import enqueue
from anime_job_management import manage
from anime_cancel_cleanup import prepare,preview_live,cleanup_torrents

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
        self.db.execute("""CREATE TABLE notifications
            (id INTEGER,info_hash TEXT)""")
        self.db.execute("INSERT INTO notifications VALUES (7,?)",(H,))
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
        self.assertEqual(self.db.execute(
            "SELECT status FROM daemon_job_cleanup_review").fetchone()[0],
            "TORRENTS_REMOVED")
        self.assertEqual(cleanup_torrents(self.db,self.jid,self.qb,approved=True),[(H,"ALREADY_REMOVED")])
        self.assertEqual(self.qb.removed,[H])

    def test_timeout_requires_manual_review(self):
        self.qb.fail=True
        with self.assertRaises(OSError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_job_cleanup_attempts").fetchone()[0],"UNCERTAIN")
        self.assertEqual(self.db.execute(
            "SELECT status FROM daemon_job_cleanup_review").fetchone()[0],
            "CLEANUP_NEEDED")
        preview=preview_live(self.db,self.jid,self.qb)
        self.assertTrue(preview["can_remove_torrents"])
        self.assertTrue(preview["records"][0]["reconcile_only"])
        self.assertEqual(cleanup_torrents(
            self.db,self.jid,self.qb,approved=True),[(H,"ABSENT")])
        self.assertEqual(len(self.qb.removed),1)
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_job_cleanup_attempts").fetchone()[0],"ABSENT")

    def test_other_notification_hash_blocks_even_without_recovery_row(self):
        self.db.execute("INSERT INTO notifications VALUES (8,?)",(H,))
        self.assertFalse(prepare(self.db,self.jid)["can_remove_torrents"])
        with self.assertRaises(ValueError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(self.qb.removed,[])

    def test_explicit_file_cleanup_only_under_verified_download_root(self):
        with tempfile.TemporaryDirectory() as root:
            download=Path(root)/"downloads"
            trial=Path(root)/"trial"
            download.mkdir();trial.mkdir()
            target=download/"episode.mkv"
            target.write_bytes(b"only this source")
            class FilesQB(MockQB):
                def torrent_details(self,h):
                    return {"hash":h,"save_path":str(download),"state":"pausedDL"}
                def torrent_files(self,h):
                    return [{"name":"episode.mkv","size":len(target.read_bytes())}]
                def torrent_inventory(self):
                    return [{"hash":H,"save_path":str(download)}]
                def remove_torrent(self,h,*,delete_files):
                    self.removed.append((h,delete_files))
                    if delete_files: target.unlink()
                    self.record=None
            qb=FilesQB()
            result=cleanup_torrents(self.db,self.jid,qb,approved=True,
                delete_download_files=True,download_root=download,trial_root=trial)
            self.assertEqual(result,[(H,"REMOVED")])
            self.assertFalse(target.exists())
            self.assertEqual(qb.removed,[(H,True)])
            self.assertEqual(self.db.execute(
                "SELECT status FROM daemon_job_cleanup_review").fetchone()[0],
                "DOWNLOADS_CLEARED")
            self.assertEqual(cleanup_torrents(self.db,self.jid,qb,approved=True,
                delete_download_files=True,download_root=download,trial_root=trial),
                [(H,"ALREADY_REMOVED")])
            self.assertEqual(qb.removed,[(H,True)])

    def test_file_replacement_before_final_delete_is_detected(self):
        with tempfile.TemporaryDirectory() as root:
            download=Path(root)/"downloads";trial=Path(root)/"trial"
            download.mkdir();trial.mkdir()
            target=download/"episode.mkv"
            target.write_bytes(b"same-size-a")
            class ChangedQB(MockQB):
                calls=0
                def torrent_identity(self,h):
                    self.calls+=1
                    if self.calls==2:
                        replacement=download/"replacement.mkv"
                        replacement.write_bytes(b"same-size-b")
                        replacement.replace(target)
                    return self.record
                def torrent_details(self,h):
                    return {"hash":h,"save_path":str(download),"state":"pausedDL"}
                def torrent_files(self,h):
                    return [{"name":"episode.mkv","size":11}]
                def torrent_inventory(self):
                    return [{"hash":H,"save_path":str(download)}]
            qb=ChangedQB()
            with self.assertRaisesRegex(ValueError,"manifest changed"):
                cleanup_torrents(self.db,self.jid,qb,approved=True,
                    delete_download_files=True,download_root=download,
                    trial_root=trial)
            self.assertEqual(qb.removed,[])
            self.assertTrue(target.is_file())
            self.assertEqual(self.db.execute(
                "SELECT state FROM daemon_job_cleanup_attempts").fetchone()[0],
                "UNCERTAIN")

    def test_file_deletion_refuses_unstopped_torrent_without_side_effects(self):
        with tempfile.TemporaryDirectory() as root:
            download=Path(root)/"downloads"
            trial=Path(root)/"trial"
            download.mkdir();trial.mkdir()
            source=download/"episode.mkv"
            source.write_bytes(b"preserve")
            class ActiveQB(MockQB):
                def torrent_details(self,h):
                    return {"hash":h,"save_path":str(download),"state":"downloading"}
                def torrent_files(self,h):
                    return [{"name":"episode.mkv"}]
                def torrent_inventory(self):
                    return [{"hash":H,"save_path":str(download)}]
            with self.assertRaisesRegex(ValueError,"Stop the torrent"):
                cleanup_torrents(self.db,self.jid,ActiveQB(),approved=True,
                    delete_download_files=True,download_root=download,trial_root=trial)
            self.assertEqual(source.read_bytes(),b"preserve")

    def test_uncertain_cleanup_never_resends_when_hash_still_present(self):
        self.qb.fail=True
        # A lost acknowledgement with qB still showing the torrent must
        # not authorize a second destructive request.
        def fail_without_removing(h,*,delete_files):
            self.qb.removed.append(h)
            raise OSError("connection dropped")
        self.qb.remove_torrent=fail_without_removing
        with self.assertRaises(OSError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertIsNotNone(self.qb.torrent_identity(H))
        with self.assertRaisesRegex(ValueError,"manual verification"):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)
        self.assertEqual(self.qb.removed,[H])

    def test_unproven_status_blocks(self):
        self.db.execute("UPDATE qb_torrent_ownership SET status='UNCERTAIN'")
        self.assertFalse(prepare(self.db,self.jid)["can_remove_torrents"])
        with self.assertRaises(ValueError):
            cleanup_torrents(self.db,self.jid,self.qb,approved=True)

if __name__=="__main__":
    unittest.main()
