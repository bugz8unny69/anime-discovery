import sqlite3
import unittest
from dataclasses import replace
from cancellation_claims import install, inspect
from cancellation_orchestration import Observation, enqueue_outbox, simulate_one, OrchestrationError
from cancellation_preflight import Attempt, Torrent
from trial_transition import create_schema

H='a'*40

def setup():
    db=sqlite3.connect(':memory:', isolation_level=None)
    create_schema(db)
    install(db)
    db.execute("INSERT INTO trial_state VALUES(7,'KEPT',1,1,3,1,1)")
    db.execute("INSERT INTO trial_attempts VALUES(9,7,'CANCEL_REQUESTED')")
    db.execute("INSERT INTO trial_decisions VALUES(7,'KEEP',3)")
    db.execute("INSERT INTO cancellation_outbox VALUES(9,7,'PENDING')")
    return db

def observation(*args, inventory=()):
    sid, aid, h=args
    return Observation(Attempt(aid,sid,h,'CANCEL_PENDING',1),10,True,1,inventory,True)

class OrchestrationTests(unittest.TestCase):
    def setUp(self):
        self.db=setup()
    def tearDown(self):
        self.db.close()
    def queue(self):
        return enqueue_outbox(self.db,{9:(7,H)})[0]
    def test_enqueue_and_absent_simulation(self):
        jid=self.queue()
        result=simulate_one(self.db,observation,now=100)
        self.assertEqual((result['state'],result['simulated']),('DONE',True))
        self.assertEqual(inspect(self.db,jid)[0],'DONE')
    def test_no_external_action(self):
        self.queue()
        result=simulate_one(self.db,lambda *args: observation(*args,inventory=(Torrent(H,'downloading'),)),now=100)
        self.assertEqual(result['outcome'],'RETRY')
        self.assertFalse(result['external_action_performed'])
    def test_retry_delay(self):
        self.queue()
        fn=lambda *args: observation(*args,inventory=(Torrent(H,'downloading'),))
        simulate_one(self.db,fn,now=100)
        self.assertIsNone(simulate_one(self.db,fn,now=159))
        self.assertEqual(simulate_one(self.db,fn,now=160)['state'],'PENDING')
    def test_idempotent_queue(self):
        self.assertEqual(self.queue(),self.queue())
        self.assertEqual(self.db.execute('SELECT count(*) FROM cancellation_jobs').fetchone()[0],1)
    def test_missing_binding(self):
        with self.assertRaises(OrchestrationError): enqueue_outbox(self.db,{})
    def test_wrong_series(self):
        with self.assertRaises(OrchestrationError): enqueue_outbox(self.db,{9:(8,H)})
    def test_bad_hash(self):
        with self.assertRaises(OrchestrationError): enqueue_outbox(self.db,{9:(7,'bad')})
    def test_stale_outbox(self):
        self.db.execute("UPDATE trial_attempts SET status='FINISHED' WHERE attempt_id=9")
        with self.assertRaises(OrchestrationError): self.queue()
    def test_wrong_attempt_observation_blocks(self):
        jid=self.queue()
        result=simulate_one(self.db,lambda *args: replace(observation(*args),attempt=Attempt(10,7,H,'CANCEL_PENDING',1)),now=100)
        self.assertEqual(result['state'],'BLOCKED')
        self.assertEqual(inspect(self.db,jid)[0],'BLOCKED')
    def test_revoked_decision_blocks(self):
        self.queue()
        result=simulate_one(self.db,lambda *args: replace(observation(*args),decision_active=False),now=100)
        self.assertEqual(result['state'],'BLOCKED')
    def test_stale_generation_blocks(self):
        self.queue()
        result=simulate_one(self.db,lambda *args: replace(observation(*args),current_generation=2),now=100)
        self.assertEqual(result['state'],'BLOCKED')
    def test_unfresh_inventory_blocks(self):
        self.queue()
        result=simulate_one(self.db,lambda *args: replace(observation(*args),fresh_inventory=False),now=100)
        self.assertEqual(result['state'],'BLOCKED')
    def test_invalid_observer_blocks(self):
        self.queue()
        self.assertEqual(simulate_one(self.db,lambda *args: None,now=100)['state'],'BLOCKED')
    def test_no_job(self):
        self.assertIsNone(simulate_one(self.db,observation,now=100))
    def test_no_production_outbox_ack(self):
        self.queue()
        simulate_one(self.db,observation,now=100)
        self.assertEqual(self.db.execute('SELECT state FROM cancellation_outbox').fetchone()[0],'PENDING')
        self.assertEqual(self.db.execute('SELECT status FROM trial_attempts').fetchone()[0],'CANCEL_REQUESTED')

if __name__=='__main__': unittest.main(verbosity=2)
