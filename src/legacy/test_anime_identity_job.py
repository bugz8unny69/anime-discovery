"""Queue-based identity worker cutover regression tests: offline only."""
import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from anime_fresh_database import initialize
from anime_identity_job import handler_factory, recover_pending
from anime_job_lineage import enqueue_linked
from anime_async_daemon import claim, finish


class IdentityJobTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/"data.sqlite"
        initialize(self.path)
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.addCleanup(self.db.close)
        self.nid=self.db.execute("""INSERT INTO notifications
            (source,release_name,source_guid,info_hash,received_at,status)
            VALUES('autobrr','Example S01E02','notify-1',?,100,'IDENTIFYING')""",
            ("a"*40,)).lastrowid

    def _handler(self):
        return handler_factory(self.path,lambda job: ({},{}))

    def test_recovery_is_idempotent_and_preserves_notification(self):
        recover_pending(self.path)
        recover_pending(self.path)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_jobs WHERE kind='identity_resolution'"
            ).fetchone()[0],1)
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)
            ).fetchone()[0],"IDENTIFYING")

    def test_identity_job_finishes_without_following_downstream_work(self):
        enqueue_linked(self.db,"identity_resolution","notification:"+str(self.nid),
                       json.dumps({"notification_id":self.nid}),notification_id=self.nid)
        job=claim(self.db,now=100,allowed_kinds=["identity_resolution"])
        with patch("anime_identity_job.check_once") as verify:
            def resolved(db,settings,secrets,*,notification_id):
                db.execute("UPDATE notifications SET status='EXCLUDED_TRIAL_WINDOW' WHERE id=?",
                           (notification_id,))
                return {"processed":1,"pending_retries":0}
            verify.side_effect=resolved
            self.assertEqual(asyncio.run(self._handler()(job)),"DONE")
        finish(self.db,job["id"],job["lease_token"],"DONE",now=100)
        self.assertEqual(self.db.execute(
            "SELECT state FROM daemon_jobs WHERE id=?",(job["id"],)).fetchone()[0],"DONE")

    def test_retryable_identity_lookup_deferred_without_review(self):
        enqueue_linked(self.db,"identity_resolution","notification:"+str(self.nid),
                       json.dumps({"notification_id":self.nid}),notification_id=self.nid)
        job=claim(self.db,now=100,allowed_kinds=["identity_resolution"])
        with patch("anime_identity_job.check_once",
                   return_value={"processed":1,"pending_retries":1}):
            self.assertEqual(asyncio.run(self._handler()(job)),"DEFERRED")
        self.assertEqual(self.db.execute(
            "SELECT status FROM notifications WHERE id=?",(self.nid,)
            ).fetchone()[0],"IDENTIFYING")


if __name__=="__main__":
    unittest.main()
