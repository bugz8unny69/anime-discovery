import sqlite3
import unittest
from dataclasses import replace
from trial_decision_gate import DecisionError, plan_trial_decision
from trial_transition import create_schema, snapshot, commit_decision, acknowledge_cancellation

class TrialTransitionTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:', isolation_level=None)
        create_schema(self.db)
        self.db.execute("INSERT INTO trial_state VALUES(7,'TRIAL',1,1,3,1,1)")
        self.db.executemany("INSERT INTO trial_attempts VALUES(?,7,'ACTIVE')", [(4,), (8,), (9,)])
        self.plan = plan_trial_decision(snapshot(self.db, 7), 'KEEP')

    def tearDown(self):
        self.db.close()

    def test_keep_early_and_outbox(self):
        self.assertEqual(commit_decision(self.db,self.plan), 'COMMITTED')
        self.assertEqual(snapshot(self.db,7).status,'KEPT')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cancellation_outbox').fetchone()[0],3)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM trial_attempts WHERE status='CANCEL_REQUESTED'").fetchone()[0],3)

    def test_reject_early(self):
        plan=plan_trial_decision(snapshot(self.db,7),'REJECT')
        self.assertEqual(commit_decision(self.db,plan),'COMMITTED')
        self.assertEqual(snapshot(self.db,7).status,'REJECTED')

    def test_retry_same_decision(self):
        commit_decision(self.db,self.plan)
        self.assertEqual(commit_decision(self.db,self.plan),'ALREADY_COMMITTED')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cancellation_outbox').fetchone()[0],3)

    def test_conflicting_decision(self):
        commit_decision(self.db,self.plan)
        with self.assertRaises(DecisionError):
            commit_decision(self.db,replace(self.plan,action='REJECT'))

    def test_stale_revision(self):
        self.db.execute('UPDATE trial_state SET mapping_revision=4 WHERE series_id=7')
        with self.assertRaises(DecisionError):
            commit_decision(self.db,self.plan)
        self.assertEqual(snapshot(self.db,7).status,'TRIAL')

    def test_stale_attempt(self):
        self.db.execute("UPDATE trial_attempts SET status='FINISHED' WHERE attempt_id=9")
        with self.assertRaises(DecisionError):
            commit_decision(self.db,self.plan)
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM trial_decisions').fetchone()[0],0)

    def test_tampered_plan(self):
        with self.assertRaises(DecisionError):
            commit_decision(self.db,replace(self.plan,cancel_attempts=()))

    def test_rollback_on_outbox_failure(self):
        self.db.execute('''CREATE TRIGGER fail_outbox BEFORE INSERT ON cancellation_outbox
                           BEGIN SELECT RAISE(ABORT,'forced'); END''')
        with self.assertRaises(sqlite3.IntegrityError):
            commit_decision(self.db,self.plan)
        self.assertEqual(snapshot(self.db,7).status,'TRIAL')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM trial_decisions').fetchone()[0],0)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM trial_attempts WHERE status='ACTIVE'").fetchone()[0],3)

    def test_acknowledgement_idempotence(self):
        commit_decision(self.db,self.plan)
        self.assertEqual(acknowledge_cancellation(self.db,4),'ACKNOWLEDGED')
        self.assertEqual(acknowledge_cancellation(self.db,4),'ALREADY_ACKNOWLEDGED')
        self.assertEqual(self.db.execute('SELECT status FROM trial_attempts WHERE attempt_id=4').fetchone()[0],'CANCELLED')

    def test_acknowledgement_without_intent(self):
        with self.assertRaises(DecisionError):
            acknowledge_cancellation(self.db,4)

    def test_no_attempts(self):
        self.db.execute("UPDATE trial_attempts SET status='FINISHED'")
        plan=plan_trial_decision(snapshot(self.db,7),'KEEP')
        self.assertEqual(commit_decision(self.db,plan),'COMMITTED')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM cancellation_outbox').fetchone()[0],0)

    def test_episode_one_required(self):
        self.db.execute('UPDATE trial_state SET episode_one_verified=0 WHERE series_id=7')
        with self.assertRaises(DecisionError):
            commit_decision(self.db,self.plan)

if __name__ == '__main__':
    unittest.main(verbosity=2)
