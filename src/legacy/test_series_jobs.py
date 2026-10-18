import json, sqlite3, tempfile, unittest
from pathlib import Path
from series_jobs import reconcile
class IntegrationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory(); p=Path(self.tmp.name); self.inbox=p/'inbox.db';self.ver=p/'verify.db';self.jobs=p/'jobs.db'
  with sqlite3.connect(self.inbox) as d:d.execute('CREATE TABLE notifications(id INTEGER PRIMARY KEY, info_hash TEXT)')
  with sqlite3.connect(self.ver) as d:d.execute('CREATE TABLE episode_verification_v16(notification_id INTEGER PRIMARY KEY,verified INTEGER,evidence_json TEXT)')
 def tearDown(self):self.tmp.cleanup()
 def add(self,nid,ep,verified=True,blockers=None):
  with sqlite3.connect(self.inbox) as d:d.execute('INSERT INTO notifications VALUES(?,?)',(nid,f'{nid:040x}'))
  data={'proposed_mapping':{'tvdb_id':389597,'tvdb_season':1,'tvdb_episode':ep},'episode_identity_verified':verified,'blockers':blockers or []}
  with sqlite3.connect(self.ver) as d:d.execute('INSERT INTO episode_verification_v16 VALUES(?,?,?)',(nid,int(verified),json.dumps(data)))
 def test_ep6_creates_five_search_jobs(self):
  self.add(1,6); r=reconcile(self.inbox,self.ver,self.jobs);self.assertEqual((r['search_required'],r['verified_candidates']),(5,1))
 def test_mapping_blocker_preserved_and_gaps_still_created(self):
  self.add(1,2,False,['EPISODE_ORDERING_MAPPING_NOT_CONFIRMED']);r=reconcile(self.inbox,self.ver,self.jobs);self.assertEqual((r['blocked'],r['search_required']),(1,1))
 def test_duplicate_reconcile_idempotent(self):
  self.add(1,3);reconcile(self.inbox,self.ver,self.jobs);r=reconcile(self.inbox,self.ver,self.jobs);self.assertEqual((r['new_notifications_planned'],r['search_required']),(0,2))
 def test_later_webhook_fills_gap(self):
  self.add(1,3);reconcile(self.inbox,self.ver,self.jobs);self.add(2,1);r=reconcile(self.inbox,self.ver,self.jobs);self.assertEqual((r['search_required'],r['verified_candidates']),(1,2))
 def test_unmapped_evidence_not_promoted(self):
  with sqlite3.connect(self.inbox) as d:d.execute('INSERT INTO notifications VALUES(1,?)',('a'*40,))
  with sqlite3.connect(self.ver) as d:d.execute('INSERT INTO episode_verification_v16 VALUES(1,0,?)',(json.dumps({'blockers':['EPISODE_ORDERING_MAPPING_NOT_CONFIRMED']}),))
  self.assertEqual(reconcile(self.inbox,self.ver,self.jobs)['series'],0)
if __name__=='__main__':unittest.main()
