import sqlite3
import tempfile
import unittest
from pathlib import Path
from fresh_attempt_ownership import install,register,preflight,OwnershipBlocked
H='a'*40
class FreshAttemptTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=sqlite3.connect(str(Path(self.tmp.name)/'fixture.db'),isolation_level=None)
  self.db.execute('CREATE TABLE download_attempts (id INTEGER PRIMARY KEY,series_id INTEGER,season INTEGER,episode INTEGER,torrent_hash TEXT,status TEXT)')
  self.db.execute('INSERT INTO download_attempts VALUES (10,1,1,1,?,?)',(H,'QUEUED'))
  install(str(Path(self.tmp.name)/'fixture.db'),self.db)
 def tearDown(self): self.db.close();self.tmp.cleanup()
 def claim(self,**kwargs):
  p=dict(attempt_id=10,series_id=1,episode=1,generation=1,torrent_hash=H,creation_receipt={'source':'controller-add','attempt_id':10,'generation':1,'hash':H},inventory_before=set(),inventory_after={H})
  p.update(kwargs);return register(str(Path(self.tmp.name)/'fixture.db'),self.db,**p)
 def test_valid_and_fence(self):
  self.claim();r=preflight(str(Path(self.tmp.name)/'fixture.db'),self.db,attempt_id=10,generation=1,torrent_hash=H,inventory_hashes={H});self.assertFalse(r['external_mutation_authorized'])
 def test_preexisting_hash(self):
  with self.assertRaises(OwnershipBlocked):self.claim(inventory_before={H})
 def test_missing_after(self):
  with self.assertRaises(OwnershipBlocked):self.claim(inventory_after=set())
 def test_receipt_mismatch(self):
  with self.assertRaises(OwnershipBlocked):self.claim(creation_receipt={'source':'controller-add','attempt_id':11,'generation':1,'hash':H})
 def test_superseded(self):
  self.db.execute('INSERT INTO download_attempts VALUES (11,1,1,1,?,?)',('b'*40,'QUEUED'))
  with self.assertRaises(OwnershipBlocked):self.claim()
 def test_superseded_after_registration(self):
  self.claim();self.db.execute('INSERT INTO download_attempts VALUES (11,1,1,1,?,?)',('b'*40,'QUEUED'))
  with self.assertRaises(OwnershipBlocked):preflight(str(Path(self.tmp.name)/'fixture.db'),self.db,attempt_id=10,generation=1,torrent_hash=H,inventory_hashes={H})
 def test_wrong_generation(self):
  self.claim()
  with self.assertRaises(OwnershipBlocked):preflight(str(Path(self.tmp.name)/'fixture.db'),self.db,attempt_id=10,generation=2,torrent_hash=H,inventory_hashes={H})
 def test_no_duplicate_registration(self):
  self.claim()
  with self.assertRaises(OwnershipBlocked):self.claim()
 def test_no_unregistered_fence(self):
  with self.assertRaises(OwnershipBlocked):preflight(str(Path(self.tmp.name)/'fixture.db'),self.db,attempt_id=10,generation=1,torrent_hash=H,inventory_hashes={H})
 def test_episode_limit(self):
  with self.assertRaises(OwnershipBlocked):self.claim(episode=7)
 def test_revoked(self):
  self.claim();self.db.execute("UPDATE fresh_attempt_ownership SET state='REVOKED'")
  with self.assertRaises(OwnershipBlocked):preflight(str(Path(self.tmp.name)/'fixture.db'),self.db,attempt_id=10,generation=1,torrent_hash=H,inventory_hashes={H})
if __name__=='__main__':unittest.main()
