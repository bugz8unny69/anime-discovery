import sqlite3
import tempfile
import unittest
from pathlib import Path
from cancellation_claims import install,enqueue,claim,finish,inspect,ClaimError
H='a'*40

class ClaimsTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:',isolation_level=None)
        install(self.db)
        self.jid=enqueue(self.db,7,101,H)
    def tearDown(self): self.db.close()
    def test_enqueue_idempotent(self): self.assertEqual(enqueue(self.db,7,101,H),self.jid)
    def test_collision(self):
        with self.assertRaises(ClaimError): enqueue(self.db,8,101,H)
    def test_invalid_input(self):
        for args in [(0,1,H),(1,0,H),(1,1,'Z'*40),(1,1,'a'*39),(True,1,H)]:
            with self.subTest(args=args),self.assertRaises(ClaimError): enqueue(self.db,*args)
    def test_claim_once(self):
        self.assertIsNotNone(claim(self.db,now=100))
        self.assertIsNone(claim(self.db,now=101))
    def test_lease_expiry_reclaim(self):
        old=claim(self.db,now=100,lease_seconds=10)
        new=claim(self.db,now=110)
        self.assertEqual(new['generation'],old['generation']+1)
        with self.assertRaises(ClaimError): finish(self.db,old,'CONFIRMED_ABSENT',now=111)
    def test_finish_done(self):
        c=claim(self.db,now=100)
        self.assertEqual(finish(self.db,c,'CONFIRMED_ABSENT',now=101),'DONE')
        self.assertIsNone(claim(self.db,now=200))
    def test_finish_blocked(self):
        c=claim(self.db,now=100)
        self.assertEqual(finish(self.db,c,'BLOCKED',now=101),'BLOCKED')
        self.assertIsNone(claim(self.db,now=200))
    def test_retry_backoff(self):
        c=claim(self.db,now=100)
        finish(self.db,c,'RETRY',now=101,retry_seconds=30)
        self.assertIsNone(claim(self.db,now=130))
        self.assertIsNotNone(claim(self.db,now=131))
    def test_retry_limit(self):
        c=claim(self.db,now=100,max_tries=2)
        finish(self.db,c,'RETRY',now=101,retry_seconds=1)
        c=claim(self.db,now=102,max_tries=2)
        finish(self.db,c,'RETRY',now=103,retry_seconds=1)
        self.assertIsNone(claim(self.db,now=104,max_tries=2))
    def test_expired_finish(self):
        c=claim(self.db,now=100,lease_seconds=10)
        with self.assertRaises(ClaimError): finish(self.db,c,'CONFIRMED_ABSENT',now=110)
    def test_wrong_token(self):
        c=claim(self.db,now=100)
        with self.assertRaises(ClaimError): finish(self.db,{**c,'lease_token':'b'*32},'CONFIRMED_ABSENT',now=101)
    def test_wrong_generation(self):
        c=claim(self.db,now=100)
        with self.assertRaises(ClaimError): finish(self.db,{**c,'generation':2},'CONFIRMED_ABSENT',now=101)
    def test_invalid_outcome(self):
        c=claim(self.db,now=100)
        with self.assertRaises(ClaimError): finish(self.db,c,'DELETED_FILES',now=101)
    def test_invalid_clock(self):
        with self.assertRaises(ClaimError): claim(self.db,now=-1)
    def test_audit_immutable(self):
        claim(self.db,now=100)
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM cancellation_job_events')
    def test_rollback_audit_failure(self):
        self.db.execute('''CREATE TRIGGER stop_event BEFORE INSERT ON cancellation_job_events BEGIN SELECT RAISE(ABORT,'stop'); END''')
        with self.assertRaises(sqlite3.IntegrityError): claim(self.db,now=100)
        self.assertEqual(inspect(self.db,self.jid)[0],'PENDING')
    def test_multiple_jobs(self):
        j2=enqueue(self.db,7,102,'b'*40)
        self.assertEqual(claim(self.db,now=100)['job_id'],self.jid)
        self.assertEqual(claim(self.db,now=100)['job_id'],j2)
    def test_persistent_recovery(self):
        with tempfile.TemporaryDirectory() as d:
            path=str(Path(d)/'test.db')
            a=sqlite3.connect(path,isolation_level=None);install(a)
            jid=enqueue(a,7,101,H)
            old=claim(a,now=100,lease_seconds=10);a.close()
            b=sqlite3.connect(path,isolation_level=None)
            new=claim(b,now=110)
            self.assertEqual(new['generation'],old['generation']+1)
            self.assertEqual(inspect(b,jid)[0],'LEASED')
            b.close()

if __name__=='__main__':
    unittest.main(verbosity=2)
