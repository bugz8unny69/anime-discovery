import unittest
from pathlib import Path
from integration_transaction_rehearsal import build_fixture, ContractError
from mapping_lifecycle_rehearsal import install as install_mapping,create_draft,add_entry,approve,revoke
from trial_mapping_integration import install as install_decisions
from verified_trial_decision import install,sign_test_decision,record_synthetic_observation,decide_authenticated

INSPECTION=Path(__file__).with_name('anime-integration-inspection.txt')
KEY=b'k'*32
NOW=1792038645

class VerifiedDecisionTests(unittest.TestCase):
    def setUp(self):
        self.db=build_fixture(INSPECTION.read_text())
        install_mapping(self.db);install_decisions(self.db);install(self.db)
        self.d=create_draft(self.db,series_id=9001,binding_id=9201,revision=2,evidence_digest='e'*64,actor='fixture')
        add_entry(self.db,self.d,27,1)
        approve(self.db,self.d,actor='fixture',trusted_evidence_verified=True)
        self.db.execute("INSERT INTO download_attempts(id,series_id,season,episode,torrent_hash,release_title,status) VALUES(9100,9001,1,1,?,'Episode One','COMPLETED')",('f'*40,))
        self.db.execute("INSERT INTO staged_episodes(series_id,season,episode,attempt_id,status,staged_path) VALUES(9001,1,1,9100,'STAGED','/synthetic/ep1.mkv')")
        self.db.execute("INSERT INTO file_observations(series_id,season,episode,staged_path,size_bytes,mtime_ns,first_observed_at,last_observed_at) VALUES(9001,1,1,'/synthetic/ep1.mkv',1000,123,1,2)")
        self.db.commit()
    def tearDown(self):self.db.close()
    def proof(self,observed_at=NOW):
        result = record_synthetic_observation(self.db,series_id=9001,mapping_id=self.d,attempt_id=9100,observed_at=observed_at)
        self.db.commit()
        return result
    def envelope(self,**changes):
        kw=dict(series_id=9001,mapping_id=self.d,action='KEEP',nonce='N'*20,issued_at=NOW-10,expires_at=NOW+100)
        kw.update(changes)
        return sign_test_decision(KEY,**kw)
    def decide(self,**kw):
        return decide_authenticated(self.db,series_id=9001,mapping_id=self.d,envelope=self.envelope(),key=KEY,now=NOW,**kw)
    def test_happy_keep_and_atomic_outbox(self):
        self.proof();self.decide()
        self.assertEqual(self.db.execute('SELECT count(*) FROM cancellation_jobs_v2').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT count(*) FROM trial_nonces_v4').fetchone()[0],1)
    def test_reject(self):
        self.proof();decide_authenticated(self.db,series_id=9001,mapping_id=self.d,envelope=self.envelope(action='REJECT'),key=KEY,now=NOW)
        self.assertEqual(self.db.execute('SELECT action FROM trial_decisions_v2').fetchone()[0],'REJECT')
    def test_no_proof(self):
        with self.assertRaises(ContractError):self.decide()
    def test_stale_proof(self):
        self.proof(NOW-301)
        with self.assertRaises(ContractError):self.decide()
    def test_future_proof(self):
        self.proof(NOW+1)
        with self.assertRaises(ContractError):self.decide()
    def test_changed_size(self):
        self.proof();self.db.execute('UPDATE file_observations SET size_bytes=1001');self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_changed_mtime(self):
        self.proof();self.db.execute('UPDATE file_observations SET mtime_ns=124');self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_changed_path(self):
        self.proof();self.db.execute("UPDATE file_observations SET staged_path='/different'");self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_attempt_failed(self):
        self.proof();self.db.execute("UPDATE download_attempts SET status='FAILED' WHERE id=9100");self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_mapping_revoked(self):
        self.proof();revoke(self.db,self.d,actor='fixture')
        with self.assertRaises(ContractError):self.decide()
    def test_identity_revoked(self):
        self.proof();self.db.execute("UPDATE identity_bindings SET state='REVOKED' WHERE id=9201");self.db.commit()
        with self.assertRaises(ContractError):self.decide()
    def test_wrong_key(self):
        self.proof()
        with self.assertRaises(ContractError):decide_authenticated(self.db,series_id=9001,mapping_id=self.d,envelope=self.envelope(),key=b'Z'*32,now=NOW)
    def test_wrong_target(self):
        self.proof()
        with self.assertRaises(ContractError):decide_authenticated(self.db,series_id=9001,mapping_id=self.d,envelope=self.envelope(mapping_id=self.d+1),key=KEY,now=NOW)
    def test_expired(self):
        self.proof()
        with self.assertRaises(ContractError):decide_authenticated(self.db,series_id=9001,mapping_id=self.d,envelope=self.envelope(),key=KEY,now=NOW+200)
    def test_tampered_action(self):
        self.proof();e=self.envelope();e['payload']['action']='REJECT'
        with self.assertRaises(ContractError):decide_authenticated(self.db,series_id=9001,mapping_id=self.d,envelope=e,key=KEY,now=NOW)
    def test_replay(self):
        self.proof();self.decide()
        with self.assertRaises(ContractError):self.decide()
    def test_rollback(self):
        self.proof()
        for step in ('decision','outbox','audit'):
            with self.subTest(step=step):
                with self.assertRaises(RuntimeError):self.decide(fail_at=step)
                for table in ('trial_decisions_v2','cancellation_jobs_v2','trial_nonces_v4','integration_audit_v2'):
                    self.assertEqual(self.db.execute('SELECT count(*) FROM '+table).fetchone()[0],0)
    def test_no_live_file(self):
        self.assertEqual(self.db.execute('PRAGMA database_list').fetchone()[2],'')
    def test_foreign_keys(self):
        self.proof();self.decide()
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_immutable_proof(self):
        self.proof()
        with self.assertRaises(Exception):self.db.execute('DELETE FROM verified_media_v4')
        self.db.rollback()

if __name__=='__main__':unittest.main()
