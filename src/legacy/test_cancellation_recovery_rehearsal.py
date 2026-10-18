import unittest
from pathlib import Path
from integration_transaction_rehearsal import build_fixture,ContractError
from mapping_lifecycle_rehearsal import install as mapping_install,create_draft,add_entry,approve
from trial_mapping_integration import install as decision_install,decide
from cancellation_recovery_rehearsal import install,seed_jobs,claim,evaluate,Inventory,report

INSPECTION=Path(__file__).with_name('anime-integration-inspection.txt')
NOW=10000

class CancellationRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=build_fixture(INSPECTION.read_text())
        mapping_install(self.db);decision_install(self.db);install(self.db)
        draft=create_draft(self.db,series_id=9001,binding_id=9201,revision=2,evidence_digest='e'*64,actor='fixture')
        add_entry(self.db,draft,27,1)
        approve(self.db,draft,actor='fixture',trusted_evidence_verified=True)
        decide(self.db,series_id=9001,draft_id=draft,action='KEEP',actor='fixture',episode_one_verified=True)
        seed_jobs(self.db)
    def tearDown(self):self.db.close()
    def obs(self,c,present=False,**changes):
        job=self.db.execute('SELECT attempt_id,torrent_hash FROM cancellation_jobs_v2 WHERE id=?',(c[0],)).fetchone()
        kw=dict(torrent_hash=job[1],present=present,attempt_id=job[0],generation=c[1],observed_at=NOW)
        kw.update(changes)
        return Inventory(**kw)
    def test_jobs_seeded(self):self.assertEqual(report(self.db),{'PENDING':2})
    def test_idempotent_seed(self):seed_jobs(self.db);self.assertEqual(report(self.db),{'PENDING':2})
    def test_claim(self):self.assertEqual(claim(self.db,now=NOW)[1],1)
    def test_absent_confirmed_synthetically(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c),now=NOW),'DONE')
    def test_present_never_completes(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c,True),now=NOW),'PENDING')
    def test_retry_after_backoff(self):
        c=claim(self.db,now=NOW);evaluate(self.db,c,self.obs(c,True),now=NOW)
        self.assertEqual(claim(self.db,now=NOW)[0],2)
        self.assertEqual(claim(self.db,now=NOW),None)
        self.assertEqual(claim(self.db,now=NOW+60)[0],1)
    def test_stale_lease_cannot_ack(self):
        c=claim(self.db,now=NOW,lease_seconds=2)
        c2=claim(self.db,now=NOW+2)
        self.assertEqual(c2[0],c[0]);self.assertNotEqual(c2[1],c[1])
        with self.assertRaises(ContractError):evaluate(self.db,c,self.obs(c),now=NOW+2)
    def test_expired_lease(self):
        c=claim(self.db,now=NOW,lease_seconds=1)
        with self.assertRaises(ContractError):evaluate(self.db,c,self.obs(c),now=NOW+1)
    def test_wrong_hash_blocks(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c,torrent_hash='0'*40),now=NOW),'BLOCKED')
    def test_wrong_attempt_blocks(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c,attempt_id=999),now=NOW),'BLOCKED')
    def test_generation_mismatch_retries(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c,generation=0),now=NOW),'PENDING')
    def test_stale_inventory_retries(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c,observed_at=NOW-11),now=NOW),'PENDING')
    def test_future_inventory_retries(self):
        c=claim(self.db,now=NOW);self.assertEqual(evaluate(self.db,c,self.obs(c,observed_at=NOW+1),now=NOW),'PENDING')
    def test_max_attempts(self):
        c=claim(self.db,now=NOW,max_attempts=1);evaluate(self.db,c,self.obs(c,True),now=NOW)
        self.assertEqual(claim(self.db,now=NOW+60,max_attempts=1)[0],2)
        self.assertEqual(claim(self.db,now=NOW+60,max_attempts=1),None)
    def test_immutable_audit(self):
        claim(self.db,now=NOW)
        with self.assertRaises(Exception):self.db.execute('DELETE FROM cancellation_recovery_events_v5')
        self.db.rollback()
    def test_memory_only(self):self.assertEqual(self.db.execute('PRAGMA database_list').fetchone()[2],'')
    def test_foreign_keys(self):self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_no_live_torrent_side_effect(self):
        c=claim(self.db,now=NOW);evaluate(self.db,c,self.obs(c,True),now=NOW)
        self.assertEqual(self.db.execute('SELECT status FROM download_attempts WHERE id=9101').fetchone()[0],'DOWNLOADING')

if __name__=='__main__':unittest.main()
