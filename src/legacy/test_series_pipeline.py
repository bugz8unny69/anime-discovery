import json, sqlite3, tempfile, unittest
from pathlib import Path
from series_pipeline import triage_title,process
class BatchTests(unittest.TestCase):
 def test_title_match(self): self.assertEqual(triage_title('Solo Leveling S01E01 1080p','Solo Leveling',1,1),'CANDIDATE_NEEDS_INDEPENDENT_VERIFICATION')
 def test_wrong_series(self): self.assertEqual(triage_title('Other S01E01','Solo Leveling',1,1),'REJECT_TITLE_MISMATCH')
 def test_wrong_episode(self): self.assertEqual(triage_title('Solo Leveling S01E02','Solo Leveling',1,1),'REJECT_EPISODE_MISMATCH')
 def test_unproven(self): self.assertEqual(triage_title('Solo Leveling 01','Solo Leveling',1,1),'REVIEW_EPISODE_UNPROVEN')
 def test_batch(self): self.assertEqual(triage_title('Solo Leveling S01E01-E03 batch','Solo Leveling',1,1),'REVIEW_MULTI_EPISODE')
 def test_mapping_block_does_not_block_other_job(self):
  with tempfile.TemporaryDirectory() as t:
   db=Path(t)/'jobs.db'; catalog=Path(t)/'catalog.json';catalog.write_text(json.dumps({'389597':'Solo Leveling'}))
   with sqlite3.connect(db) as c:
    c.execute('CREATE TABLE episode_jobs(tvdb_id INT,season INT,episode INT,state TEXT)')
    c.executemany('INSERT INTO episode_jobs VALUES(389597,1,?,?)',[(1,'SEARCH_REQUIRED'),(2,'BLOCKED_VERIFICATION')])
    c.execute('CREATE TABLE historical_candidates(tvdb_id INT,season INT,episode INT,candidate_key TEXT,title TEXT)')
    c.executemany('INSERT INTO historical_candidates VALUES(389597,1,1,?,?)',[('a','Solo Leveling S01E01'),('b','Other S01E01')])
   result=process(str(db),str(catalog),write=True)
   self.assertEqual(result['episodes'][0]['candidates']['CANDIDATE_NEEDS_INDEPENDENT_VERIFICATION'],1)
   self.assertEqual(result['episodes'][1]['readiness'],'BLOCKED_VERIFICATION')
   self.assertFalse(result['series'][0]['keep_ready'])
   with sqlite3.connect(db) as c: self.assertEqual(c.execute('SELECT COUNT(*) FROM candidate_triage').fetchone()[0],2)
if __name__=='__main__':unittest.main()

class AcquisitionCases(unittest.TestCase):
 def test_rejected(self):
  from series_pipeline import acquisition_decision as d
  self.assertEqual(d(verified=True,blockers=[],rejected=True,info_hash='a'*40,existing_hashes=[],owned_canonical=False,legacy_owned=False),'REPLAY_BLOCKED_REJECTED')
 def test_existing(self):
  from series_pipeline import acquisition_decision as d
  self.assertEqual(d(verified=True,blockers=[],rejected=False,info_hash='a'*40,existing_hashes=['A'*40],owned_canonical=False,legacy_owned=False),'REUSE_EXISTING_TORRENT')
 def test_blocked(self):
  from series_pipeline import acquisition_decision as d
  self.assertEqual(d(verified=False,blockers=['EPISODE_ORDERING_MAPPING_NOT_CONFIRMED'],rejected=False,info_hash='a'*40,existing_hashes=[],owned_canonical=False,legacy_owned=False),'BLOCKED_VERIFICATION')
 def test_legacy(self):
  from series_pipeline import acquisition_decision as d
  self.assertEqual(d(verified=True,blockers=[],rejected=False,info_hash='a'*40,existing_hashes=[],owned_canonical=False,legacy_owned=True),'OWNED_LEGACY_REQUIRES_SAFE_MIGRATION')
