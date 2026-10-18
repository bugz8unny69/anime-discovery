import sqlite3
import unittest
from attempt_evidence_fencing import (install,seed,record_synthetic_evidence,
    decide,cancellation_preflight,GateError)

class Rehearsal(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        install(self.db);seed(self.db)
        self.args=dict(observed_path='/synthetic/episode1.mkv',observed_size=100_000_000,observed_mtime=1234)
    def tearDown(self): self.db.close()
    def evidence(self,**kwargs): record_synthetic_evidence(self.db,11,**kwargs)
    def decision(self,**kwargs): return decide(self.db,1,'KEEP',11,**(self.args|kwargs))
    def test_missing_evidence(self):
        with self.assertRaises(GateError): self.decision()
    def test_good_evidence(self):
        self.evidence();self.assertEqual(self.decision(),'RECORDED_SIMULATION_ONLY')
    def test_later_download_active(self):
        self.evidence();self.decision();self.assertEqual(self.db.execute('SELECT count(*) FROM am_outbox').fetchone()[0],1)
    def test_idempotent(self):
        self.evidence();self.decision();self.assertEqual(self.decision(),'UNCHANGED')
    def test_conflicting_action(self):
        self.evidence();self.decision()
        with self.assertRaises(GateError): decide(self.db,1,'REJECT',11,**self.args)
    def test_stale_attempt(self):
        self.evidence()
        with self.assertRaises(GateError): decide(self.db,1,'KEEP',12,**self.args)
    def test_mapping_blocked(self):
        self.evidence();self.db.execute("UPDATE am_trials SET mapping_state='REVIEW'");self.db.commit()
        with self.assertRaises(GateError): self.decision()
    def test_file_change(self):
        self.evidence()
        with self.assertRaises(GateError): self.decision(observed_mtime=1235)
    def test_size_change(self):
        self.evidence()
        with self.assertRaises(GateError): self.decision(observed_size=100_000_001)
    def test_unstable(self):
        self.evidence(stable=False)
        with self.assertRaises(GateError): self.decision()
    def test_no_video(self):
        self.evidence(media_ok=False)
        with self.assertRaises(GateError): self.decision()
    def test_no_dual_audio(self):
        self.evidence(dual_audio_ok=False)
        with self.assertRaises(GateError): self.decision()
    def test_attempt_incomplete(self):
        self.evidence();self.db.execute("UPDATE am_attempts SET status='DOWNLOADING' WHERE id=11");self.db.commit()
        with self.assertRaises(GateError): self.decision()
    def test_rollback(self):
        self.evidence()
        with self.assertRaises(GateError): self.decision(observed_mtime=7)
        self.assertEqual(self.db.execute('SELECT count(*) FROM am_decisions').fetchone()[0],0)
    def test_fenced_preflight(self):
        self.evidence();self.decision()
        self.assertEqual(cancellation_preflight(self.db,1,observed_hash='b'*40,observed_generation=1,observed_attempt_id=12,present=True),'WOULD_REQUEST_REMOVE_WITH_DELETE_FILES_FALSE')
    def test_wrong_hash(self):
        self.evidence();self.decision()
        self.assertEqual(cancellation_preflight(self.db,1,observed_hash='c'*40,observed_generation=1,observed_attempt_id=12,present=True),'BLOCKED')
    def test_wrong_generation(self):
        self.evidence();self.decision()
        self.assertEqual(cancellation_preflight(self.db,1,observed_hash='b'*40,observed_generation=2,observed_attempt_id=12,present=True),'BLOCKED')
    def test_wrong_attempt(self):
        self.evidence();self.decision()
        self.assertEqual(cancellation_preflight(self.db,1,observed_hash='b'*40,observed_generation=1,observed_attempt_id=99,present=True),'BLOCKED')
    def test_absent(self):
        self.evidence();self.decision()
        self.assertEqual(cancellation_preflight(self.db,1,observed_hash='b'*40,observed_generation=1,observed_attempt_id=12,present=False),'ALREADY_ABSENT_SIMULATION')
    def test_no_live_qb(self):
        import inspect,attempt_evidence_fencing as m
        self.assertNotIn('requests.',inspect.getsource(m))

if __name__=='__main__':unittest.main()
