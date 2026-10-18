import unittest
from pathlib import Path
from integration_transaction_rehearsal import build_fixture,ContractError,inventory
from mapping_lifecycle_rehearsal import install,create_draft,add_entry,approve,revoke
from trial_mapping_integration import decide,install as install_decision

INSPECTION=Path(__file__).with_name('anime-integration-inspection.txt')
class IntegrationTests(unittest.TestCase):
    def setUp(self):
        self.db=build_fixture(INSPECTION.read_text());install(self.db);install_decision(self.db)
        self.d=create_draft(self.db,series_id=9001,binding_id=9201,revision=2,evidence_digest='e'*64,actor='fixture')
        add_entry(self.db,self.d,27,1)
    def tearDown(self): self.db.close()
    def approve(self): approve(self.db,self.d,actor='fixture',trusted_evidence_verified=True)
    def decide(self,**kw):
        return decide(self.db,series_id=9001,draft_id=self.d,action='KEEP',actor='fixture',episode_one_verified=True,**kw)
    def test_draft_blocked(self):
        with self.assertRaises(ContractError):self.decide()
    def test_approved_keep_atomic(self):
        self.approve();self.decide()
        self.assertEqual({k:self.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for k,t in [('trial_decisions','trial_decisions_v2'),('cancellation_jobs','cancellation_jobs_v2'),('integration_audit','integration_audit_v2')]},{'trial_decisions':1,'cancellation_jobs':2,'integration_audit':1})
    def test_approved_reject(self):
        self.approve();decide(self.db,series_id=9001,draft_id=self.d,action='REJECT',actor='fixture',episode_one_verified=True)
        self.assertEqual({k:self.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for k,t in [('trial_decisions','trial_decisions_v2'),('cancellation_jobs','cancellation_jobs_v2'),('integration_audit','integration_audit_v2')]}['cancellation_jobs'],2)
    def test_revoked_mapping_blocked(self):
        self.approve();revoke(self.db,self.d,actor='fixture')
        with self.assertRaises(ContractError):self.decide()
    def test_revoked_identity_blocked(self):
        self.approve();self.db.execute("UPDATE identity_bindings SET state='REVOKED' WHERE id=9201");self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_missing_watchability_blocked(self):
        self.approve()
        with self.assertRaises(ContractError):decide(self.db,series_id=9001,draft_id=self.d,action='KEEP',actor='fixture')
    def test_idempotent(self):
        self.approve();a=self.decide();b=self.decide();self.assertEqual(a,b)
        self.assertEqual({k:self.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for k,t in [('trial_decisions','trial_decisions_v2'),('cancellation_jobs','cancellation_jobs_v2'),('integration_audit','integration_audit_v2')]}['cancellation_jobs'],2)
    def test_conflict_blocked(self):
        self.approve();self.decide()
        with self.assertRaises(ContractError):decide(self.db,series_id=9001,draft_id=self.d,action='REJECT',actor='fixture',episode_one_verified=True)
    def test_rollback_each_step(self):
        self.approve()
        for step in ('decision','outbox','audit'):
            with self.subTest(step=step):
                with self.assertRaises(RuntimeError):self.decide(fail_at=step)
                self.assertEqual({k:self.db.execute('SELECT count(*) FROM '+t).fetchone()[0] for k,t in [('trial_decisions','trial_decisions_v2'),('cancellation_jobs','cancellation_jobs_v2'),('integration_audit','integration_audit_v2')]},{'trial_decisions':0,'cancellation_jobs':0,'integration_audit':0})
    def test_stale_series_state_blocked(self):
        self.approve();self.db.execute("UPDATE series SET status='REJECTED' WHERE id=9001");self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_no_live_series_mutation(self):
        self.approve();self.decide()
        self.assertEqual(self.db.execute('SELECT status FROM series WHERE id=9001').fetchone()[0],'PENDING_REVIEW')
    def test_foreign_key_integrity(self):
        self.approve();self.decide()
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_no_unapproved_other_mapping(self):
        self.approve()
        other=create_draft(self.db,series_id=9001,binding_id=9201,revision=3,evidence_digest='f'*64,actor='fixture')
        add_entry(self.db,other,28,1)
        with self.assertRaises(ContractError):decide(self.db,series_id=9001,draft_id=other,action='KEEP',actor='fixture',episode_one_verified=True)
if __name__=='__main__':unittest.main()
