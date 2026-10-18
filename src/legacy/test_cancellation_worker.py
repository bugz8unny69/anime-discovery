import sqlite3
import unittest
from cancellation_worker import (Torrent, create_worker_schema, bind_target,
    plan_cancellation, record_simulated_result)
from trial_transition import create_schema
from trial_decision_gate import DecisionError

H1 = 'a'*40
H2 = 'b'*40

class WorkerTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.execute('PRAGMA foreign_keys=ON')
        create_schema(self.db)
        create_worker_schema(self.db)
        self.db.execute("INSERT INTO trial_state VALUES(7,'KEPT',1,1,3,1,1)")
        self.db.execute("INSERT INTO trial_attempts VALUES(9,7,'ACTIVE')")
        bind_target(self.db, 9, H1)
        self.db.execute("UPDATE trial_attempts SET status='CANCEL_REQUESTED' WHERE attempt_id=9")
        self.db.execute("INSERT INTO cancellation_outbox VALUES(9,7,'PENDING')")
        self.db.commit()
    def tearDown(self): self.db.close()
    def test_downloading(self):
        self.assertEqual(plan_cancellation(self.db,9,[Torrent(H1,9,'DOWNLOADING')]).outcome,'WOULD_CANCEL')
    def test_paused(self):
        self.assertEqual(plan_cancellation(self.db,9,[Torrent(H1,9,'PAUSED')]).outcome,'WOULD_CANCEL')
    def test_complete_still_requires_cancel(self):
        self.assertEqual(plan_cancellation(self.db,9,[Torrent(H1,9,'COMPLETE')]).outcome,'WOULD_CANCEL')
    def test_missing(self):
        self.assertEqual(plan_cancellation(self.db,9,[]).outcome,'ALREADY_GONE')
    def test_different_attempt(self):
        with self.assertRaises(DecisionError): plan_cancellation(self.db,9,[Torrent(H1,10,'DOWNLOADING')])
    def test_other_hash_ignored(self):
        self.assertEqual(plan_cancellation(self.db,9,[Torrent(H2,10,'DOWNLOADING')]).outcome,'ALREADY_GONE')
    def test_duplicate_hash_fails(self):
        with self.assertRaises(DecisionError): plan_cancellation(self.db,9,[Torrent(H1,9,'PAUSED'),Torrent(H1,9,'PAUSED')])
    def test_unknown_state_fails(self):
        with self.assertRaises(DecisionError): plan_cancellation(self.db,9,[Torrent(H1,9,'UNKNOWN')])
    def test_no_outbox_fails(self):
        with self.assertRaises(DecisionError): plan_cancellation(self.db,10,[])
    def test_no_rebinding_after_intent(self):
        with self.assertRaises(DecisionError): bind_target(self.db,9,H2)
    def test_invalid_hash(self):
        with self.assertRaises(DecisionError): bind_target(self.db,10,'wrong')
    def test_simulated_success(self):
        inv=[Torrent(H1,9,'DOWNLOADING')]
        action=plan_cancellation(self.db,9,inv)
        self.assertEqual(record_simulated_result(self.db,action,'CANCELLED',inv),'RECORDED_SIMULATION')
        self.assertEqual(self.db.execute('SELECT state FROM cancellation_outbox').fetchone()[0],'ACKNOWLEDGED')
    def test_simulated_missing(self):
        action=plan_cancellation(self.db,9,[])
        self.assertEqual(record_simulated_result(self.db,action,'ALREADY_GONE',[]),'RECORDED_SIMULATION')
    def test_retry_idempotent(self):
        inv=[Torrent(H1,9,'PAUSED')]
        action=plan_cancellation(self.db,9,inv)
        record_simulated_result(self.db,action,'CANCELLED',inv)
        self.assertEqual(record_simulated_result(self.db,action,'CANCELLED',inv),'ALREADY_RECORDED')
    def test_changed_inventory_rolls_back(self):
        action=plan_cancellation(self.db,9,[Torrent(H1,9,'DOWNLOADING')])
        with self.assertRaises(DecisionError): record_simulated_result(self.db,action,'CANCELLED',[])
        self.assertEqual(self.db.execute('SELECT state FROM cancellation_outbox').fetchone()[0],'PENDING')
    def test_false_confirmation_rolls_back(self):
        action=plan_cancellation(self.db,9,[Torrent(H1,9,'PAUSED')])
        with self.assertRaises(DecisionError): record_simulated_result(self.db,action,'ALREADY_GONE',[Torrent(H1,9,'PAUSED')])
    def test_acknowledged_is_noop_plan(self):
        action=plan_cancellation(self.db,9,[])
        record_simulated_result(self.db,action,'ALREADY_GONE',[])
        self.assertEqual(plan_cancellation(self.db,9,[]).outcome,'ALREADY_GONE')

if __name__ == '__main__': unittest.main(verbosity=2)
