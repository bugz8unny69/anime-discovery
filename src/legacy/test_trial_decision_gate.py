import unittest
from dataclasses import replace

from trial_decision_gate import (
    TrialState,
    DecisionError,
    plan_trial_decision,
    validate_commit_preconditions,
)


class DecisionGateTests(unittest.TestCase):

    def setUp(self):
        self.state = TrialState(
            series_id=7,
            status="TRIAL",
            identity_bound=True,
            mapping_approved=True,
            mapping_revision=3,
            published_prefix=1,
            episode_one_verified=True,
            pending_attempts=(9, 4, 8),
        )

    def test_keep_after_episode_one(self):
        plan = plan_trial_decision(self.state, "KEEP")
        self.assertEqual(plan.target_status, "KEPT")
        self.assertEqual(plan.cancel_attempts, (4, 8, 9))
        self.assertTrue(plan.dry_run)

    def test_reject_after_episode_one(self):
        plan = plan_trial_decision(self.state, "REJECT")
        self.assertEqual(plan.target_status, "REJECTED")

    def test_decision_at_every_prefix(self):
        for prefix in range(1, 7):
            with self.subTest(prefix=prefix):
                state = replace(self.state, published_prefix=prefix)
                plan_trial_decision(state, "KEEP")

    def test_invalid_states(self):
        cases = [
            {"status": "KEPT"},
            {"status": "REJECTED"},
            {"status": "REVIEW"},
            {"identity_bound": False},
            {"mapping_approved": False},
            {"mapping_revision": 0},
            {"published_prefix": 0},
            {"published_prefix": 7},
            {"episode_one_verified": False},
            {"pending_attempts": (1, 1)},
            {"pending_attempts": (0,)},
        ]

        for changes in cases:
            with self.subTest(changes=changes):
                with self.assertRaises(DecisionError):
                    plan_trial_decision(
                        replace(self.state, **changes),
                        "KEEP",
                    )

    def test_invalid_actions(self):
        for action in ("keep", "DELETE", "", "APPROVE"):
            with self.subTest(action=action):
                with self.assertRaises(DecisionError):
                    plan_trial_decision(self.state, action)

    def test_commit_preconditions(self):
        plan = plan_trial_decision(self.state, "KEEP")
        validate_commit_preconditions(plan, self.state)

        changes = [
            {"status": "REJECTED"},
            {"mapping_revision": 4},
            {"identity_bound": False},
            {"mapping_approved": False},
            {"episode_one_verified": False},
            {"published_prefix": 0},
            {"pending_attempts": (9, 4)},
        ]

        for change in changes:
            with self.subTest(change=change):
                with self.assertRaises(DecisionError):
                    validate_commit_preconditions(
                        plan,
                        replace(self.state, **change),
                    )

    def test_no_pending_attempts(self):
        state = replace(self.state, pending_attempts=())
        plan = plan_trial_decision(state, "KEEP")
        self.assertEqual(plan.cancel_attempts, ())

    def test_no_state_mutation(self):
        original = self.state
        plan_trial_decision(self.state, "REJECT")
        self.assertEqual(self.state, original)


if __name__ == "__main__":
    unittest.main(verbosity=2)
