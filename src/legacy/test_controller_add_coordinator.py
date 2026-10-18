import sqlite3
import tempfile
import unittest
from pathlib import Path
from controller_add_coordinator import install, coordinate, journal_summary, AddBlocked
H='a'*40
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'fixture.db');self.lock=str(Path(self.tmp.name)/'add.lock')
  self.db=sqlite3.connect(self.path,isolation_level=None)
  self.db.execute('CREATE TABLE download_attempts (id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT)')
  self.db.execute('INSERT INTO download_attempts VALUES (10,1,1,1,?,?)',(H,'QUEUED'))
  install(self.path,self.db);self.inventory=set();self.calls=0
 def tearDown(self):self.db.close();self.tmp.cleanup()
 def add(self,h):self.calls+=1;self.inventory.add(h);return True
 def runadd(self,**kw):
  args=dict(db_path=self.path,db=self.db,attempt_id=10,series_id=1,episode=1,generation=1,torrent_hash=H,inventory=lambda:set(self.inventory),add=self.add,lock_path=self.lock,allow_external_add=True)
  args.update(kw);return coordinate(**args)
 def test_success(self):
  r=self.runadd();self.assertEqual(r['state'],'CONFIRMED');self.assertFalse(r['cancellation_authorized']);self.assertEqual(journal_summary(self.path,self.db),{'CONFIRMED':1})
 def test_disabled_default(self):
  with self.assertRaises(AddBlocked):self.runadd(allow_external_add=False)
  self.assertEqual(self.calls,0)
 def test_preexisting_not_adopted(self):
  self.inventory.add(H)
  with self.assertRaises(AddBlocked):self.runadd()
  self.assertEqual(self.calls,0)
 def test_replay_no_second_add(self):
  self.runadd()
  with self.assertRaises(AddBlocked):self.runadd()
  self.assertEqual(self.calls,1)
 def test_failed_remote_quarantine(self):
  def fail(h):self.inventory.add(h);raise TimeoutError('unknown result')
  with self.assertRaises(AddBlocked):self.runadd(add=fail)
  self.assertEqual(journal_summary(self.path,self.db),{'QUARANTINED':1})
  with self.assertRaises(AddBlocked):self.runadd()
 def test_missing_after(self):
  with self.assertRaises(AddBlocked):self.runadd(add=lambda h:True)
  self.assertEqual(journal_summary(self.path,self.db),{'QUARANTINED':1})
 def test_superseded(self):
  self.db.execute('INSERT INTO download_attempts VALUES (11,1,1,1,?,?)',('b'*40,'QUEUED'))
  with self.assertRaises(AddBlocked):self.runadd()
  self.assertEqual(self.calls,0)
 def test_attempt_mismatch(self):
  with self.assertRaises(AddBlocked):self.runadd(series_id=2)
 def test_episode_limit(self):
  with self.assertRaises(AddBlocked):self.runadd(episode=7)
 def test_duplicate_inventory(self):
  with self.assertRaises(AddBlocked):self.runadd(inventory=lambda:[H,H])
 def test_foreign_torrent_disappears(self):
  other='b'*40;self.inventory.add(other)
  def add(h):self.inventory.clear();self.inventory.add(h);return True
  with self.assertRaises(AddBlocked):self.runadd(add=add)
 def test_bad_hash(self):
  with self.assertRaises(AddBlocked):self.runadd(torrent_hash='wrong')
 def test_stale_prepared(self):
  self.db.execute('INSERT INTO controller_add_journal VALUES (10,1,1,1,?,?)',(H,'PREPARED'))
  with self.assertRaises(AddBlocked):self.runadd()
  self.assertEqual(self.calls,0)
if __name__=='__main__':unittest.main()
