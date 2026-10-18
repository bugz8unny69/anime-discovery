import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_identity_worker_v9 import process

class WorkerTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
  self.inbox=Path(self.tmp.name)/'inbox.db'; self.verified=Path(self.tmp.name)/'verified.db'
  with sqlite3.connect(self.inbox) as db:
   db.execute('CREATE TABLE notifications(id INTEGER PRIMARY KEY,status TEXT)')
   db.executemany('INSERT INTO notifications VALUES (?,?)',[(1,'UNTRUSTED'),(2,'NEEDS_REVIEW')])
 def test_read_only_without_runner(self):
  out=process(self.inbox,self.verified,5)
  self.assertEqual(out['items'][0]['action'],'SKIPPED_NON_UNTRUSTED')
  self.assertEqual(out['items'][1]['action'],'NO_RUNNER_CONFIGURED')
  self.assertFalse(self.verified.exists())
 def test_existing_identity_reused(self):
  with sqlite3.connect(self.verified) as db:
   db.execute('CREATE TABLE verified_series_identity(notification_id INTEGER,anidb_id TEXT,tvdb_id TEXT,decision TEXT,episode_identity_verified INTEGER,eligible_for_acquisition INTEGER)')
   db.execute("INSERT INTO verified_series_identity VALUES(1,'17495','389597','SERIES_VERIFIED_EPISODE_PENDING',0,0)")
  out=process(self.inbox,self.verified,5)
  self.assertEqual(out['items'][1]['action'],'SERIES_ALREADY_PERSISTED_EPISODE_PENDING')
 def test_errors_do_not_change_status(self):
  out=process(self.inbox,self.verified,5,episode_runner=lambda n: (_ for _ in ()).throw(ValueError('lookup failed')))
  self.assertEqual(out['items'][1]['action'],'ERROR_RETRY_NO_STATUS_CHANGE')
  with sqlite3.connect(self.inbox) as db:self.assertEqual(db.execute('SELECT status FROM notifications WHERE id=1').fetchone()[0],'UNTRUSTED')
 def test_unverified_does_not_persist(self):
  out=process(self.inbox,self.verified,5,True,lambda n:{'issues':['lookup error']})
  self.assertEqual(out['items'][1]['action'],'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE')
  self.assertFalse(self.verified.exists())
if __name__=='__main__': unittest.main()
