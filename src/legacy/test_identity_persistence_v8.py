import copy
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_identity_persistence_v8 import persist

BASE={'notification_id':1,'series_identity_verified':True,'episode_identity_verified':False,'eligible_for_acquisition':False,'write_performed':False,'status_unchanged':'UNTRUSTED','decision':'SERIES_VERIFIED_EPISODE_PENDING','tvdb_episode_exists':True,'series':{'anidb_id':'17495','tvdb_id':'389597','mapping_source':'https://raw.githubusercontent.com/Anime-Lists/anime-lists/master/anime-list.xml'}}
class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); self.db=Path(self.tmp.name)/'identities.db'
 def tearDown(self): self.tmp.cleanup()
 def test_dry_run_no_db(self):
  self.assertEqual(persist(self.db,BASE)['action'],'DRY_RUN_VALIDATED');self.assertFalse(self.db.exists())
 def test_insert(self):
  self.assertEqual(persist(self.db,BASE,True)['action'],'INSERTED')
  with sqlite3.connect(self.db) as db: self.assertEqual(db.execute('select episode_identity_verified,eligible_for_acquisition from verified_series_identity').fetchone(),(0,0))
 def test_idempotent(self):
  persist(self.db,BASE,True);self.assertEqual(persist(self.db,BASE,True)['action'],'UNCHANGED')
 def test_conflict_no_overwrite(self):
  persist(self.db,BASE,True);other=copy.deepcopy(BASE);other['series']['tvdb_id']='999'
  with self.assertRaisesRegex(ValueError,'IDENTITY_CONFLICT'):persist(self.db,other,True)
  with sqlite3.connect(self.db) as db:self.assertEqual(db.execute('select tvdb_id from verified_series_identity').fetchone()[0],'389597')
 def test_refuse_acquisition(self):
  other=copy.deepcopy(BASE);other['eligible_for_acquisition']=True
  with self.assertRaises(ValueError):persist(self.db,other,True)
 def test_refuse_episode_approved(self):
  other=copy.deepcopy(BASE);other['episode_identity_verified']=True
  with self.assertRaises(ValueError):persist(self.db,other,True)
 def test_refuse_bad_status(self):
  other=copy.deepcopy(BASE);other['status_unchanged']='IDENTIFIED'
  with self.assertRaises(ValueError):persist(self.db,other,True)
 def test_refuse_unrecognized_source(self):
  other=copy.deepcopy(BASE);other['series']['mapping_source']='https://example.com'
  with self.assertRaises(ValueError):persist(self.db,other,True)
 def test_evidence_update_same_pair(self):
  persist(self.db,BASE,True);other=copy.deepcopy(BASE);other['issues']=['audit note']
  self.assertEqual(persist(self.db,other,True)['action'],'EVIDENCE_UPDATED')
if __name__=='__main__':unittest.main()
