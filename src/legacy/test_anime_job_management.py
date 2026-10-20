"""Offline job administration: bounded transitions, audit and lease fencing."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_async_daemon import claim, enqueue, finish
from anime_job_management import latest_events, manage


class ManageTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"jobs.sqlite"
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.addCleanup(self.db.close)
        enqueue(self.db,"claimed_acquisition","1",'{"notification_id":1}')
        self.job_id=self.db.execute("SELECT id FROM daemon_jobs").fetchone()[0]

    def deferred(self):
        first=claim(self.db,now=100,lease_seconds=30)
        finish(self.db,first["id"],first["lease_token"],"DEFERRED",
               reason="IdentityNotReady",now=101)
        return first

    def row(self):
        return self.db.execute("""SELECT state,available_at,attempts,last_error,
                                  lease_token,lease_until
                                  FROM daemon_jobs WHERE id=?""",
                               (self.job_id,)).fetchone()

    def test_retry_now_preserves_error_payload_and_counts(self):
        self.deferred()
        initial_payload=self.db.execute(
            "SELECT payload_json FROM daemon_jobs").fetchone()[0]
        result=manage(self.db,self.job_id,"retry",
                      expected_state="DEFERRED",expected_attempts=1,now=102)
        self.assertEqual(result["state"],"READY")
        self.assertEqual(self.row(),("READY",0,1,"IdentityNotReady",None,None))
        self.assertEqual(self.db.execute("SELECT payload_json FROM daemon_jobs").fetchone()[0],
                         initial_payload)
        action=latest_events(self.db)[self.job_id]
        self.assertEqual(action["previous_error"],"IdentityNotReady")
        self.assertEqual(action["action"],"retry")
        resumed=claim(self.db,now=103,lease_seconds=30)
        self.assertEqual(resumed["id"],self.job_id)
        self.assertEqual(self.row()[2],2)
        with self.assertRaises(ValueError):
            manage(self.db,self.job_id,"cancel",expected_state="READY",
                   expected_attempts=1)

    def test_cancel_defers_no_more_and_never_calls_external_clients(self):
        self.deferred()
        result=manage(self.db,self.job_id,"cancel",
                      expected_state="DEFERRED",expected_attempts=1,now=102)
        self.assertEqual(result["state"],"BLOCKED")
        self.assertIsNone(claim(self.db,now=99999))
        self.assertEqual(self.row()[2:4],(1,"IdentityNotReady"))
        self.assertEqual(latest_events(self.db)[self.job_id]["action"],"cancel")
        with self.assertRaisesRegex(ValueError,"changed"):
            manage(self.db,self.job_id,"cancel",
                   expected_state="DEFERRED",expected_attempts=1)
        with self.assertRaises(ValueError):
            manage(self.db,self.job_id,"retry",
                   expected_state="DEFERRED",expected_attempts=1)

    def test_cancel_ready_and_needs_review(self):
        manage(self.db,self.job_id,"cancel",
               expected_state="READY",expected_attempts=0)
        self.assertIsNone(claim(self.db,now=999))
        enqueue(self.db,"series_gap_search","other","{}")
        sid=self.db.execute("SELECT id FROM daemon_jobs WHERE kind='series_gap_search'").fetchone()[0]
        entry=claim(self.db,now=100)
        finish(self.db,sid,entry["lease_token"],"NEEDS_REVIEW",now=101)
        manage(self.db,sid,"cancel",expected_state="NEEDS_REVIEW",expected_attempts=1)
        self.assertEqual(self.db.execute("SELECT state FROM daemon_jobs WHERE id=?",(sid,)).fetchone()[0],"BLOCKED")

    def test_active_leases_are_not_cancelable_even_when_expired(self):
        self.deferred()
        worker=claim(self.db,now=110,lease_seconds=30)
        self.assertIsNotNone(worker)
        for action in ("cancel","retry"):
            with self.assertRaisesRegex(ValueError,"changed"):
                manage(self.db,self.job_id,action,
                       expected_state="DEFERRED",expected_attempts=1,now=150)
        self.assertEqual(self.row()[0],"LEASED")
        # Master worker recovers expired leases via its normal claim path.
        reclaimed=claim(self.db,now=150,lease_seconds=30)
        self.assertEqual(reclaimed["id"],self.job_id)
        with self.assertRaises(ValueError):
            finish(self.db,worker["id"],worker["lease_token"],"DONE",now=150)

    def test_second_connection_rejects_stale_dashboard_action(self):
        self.deferred()
        with sqlite3.connect(self.path,isolation_level=None) as other:
            manage(other,self.job_id,"retry",
                   expected_state="DEFERRED",expected_attempts=1)
        with self.assertRaisesRegex(ValueError,"changed"):
            manage(self.db,self.job_id,"cancel",
                   expected_state="DEFERRED",expected_attempts=1)
        self.assertEqual(self.row()[0],"READY")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_job_admin_events").fetchone()[0],1)

    def test_forged_inputs_cannot_modify_jobs(self):
        self.deferred()
        for bad in (None,True,1.0,"1",-2):
            with self.subTest(id=bad),self.assertRaises(ValueError):
                manage(self.db,bad,"retry",
                       expected_state="DEFERRED",expected_attempts=1)
        for bad in ("LEASED","BLOCKED",None):
            with self.subTest(state=bad),self.assertRaises(ValueError):
                manage(self.db,self.job_id,"retry",
                       expected_state=bad,expected_attempts=1)
        with self.assertRaises(ValueError):
            manage(self.db,self.job_id,"retry",
                   expected_state="DEFERRED",expected_attempts=0)
        with self.assertRaises(ValueError):
            manage(self.db,self.job_id,"wipe",
                   expected_state="DEFERRED",expected_attempts=1)
        with self.assertRaises(ValueError):
            manage(self.db,self.job_id,"retry",
                   expected_state="DEFERRED",expected_attempts=True)
        self.assertEqual(self.row()[0],"DEFERRED")
        self.assertEqual(latest_events(self.db),{})

    def test_unrecognized_kind_cannot_be_administered(self):
        enqueue(self.db,"unsafe_handler","7","{}")
        jid=self.db.execute("SELECT id FROM daemon_jobs WHERE kind='unsafe_handler'").fetchone()[0]
        with self.assertRaisesRegex(ValueError,"Unsupported"):
            manage(self.db,jid,"cancel",expected_state="READY",expected_attempts=0)
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_jobs WHERE id=?",(jid,)).fetchone()[0],"READY")

if __name__=="__main__":
    unittest.main()
