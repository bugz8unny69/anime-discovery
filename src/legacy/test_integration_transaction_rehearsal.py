import sqlite3
import unittest
from pathlib import Path
from integration_transaction_rehearsal import (
    ContractError, build_fixture, inventory, rehearse_decision, require_memory,
)

INSPECTION = Path(__file__).with_name('anime-integration-inspection.txt')


class IntegrationTransactionTests(unittest.TestCase):
    def setUp(self):
        self.db = build_fixture(INSPECTION.read_text())

    def tearDown(self):
        self.db.close()

    def test_keep_creates_atomic_outbox(self):
        rehearse_decision(self.db)
        self.assertEqual(inventory(self.db), {'trial_decisions': 1, 'cancellation_jobs': 2, 'integration_audit': 1})
        self.assertEqual(self.db.execute('SELECT torrent_hash FROM cancellation_jobs ORDER BY attempt_id').fetchall(), [('a'*40,), ('b'*40,)])

    def test_reject(self):
        rehearse_decision(self.db, action='REJECT')
        self.assertEqual(self.db.execute('SELECT action FROM trial_decisions').fetchone()[0], 'REJECT')

    def test_idempotent_same_decision(self):
        first = rehearse_decision(self.db)
        self.assertEqual(first, rehearse_decision(self.db))
        self.assertEqual(inventory(self.db), {'trial_decisions': 1, 'cancellation_jobs': 2, 'integration_audit': 1})

    def test_conflicting_decision_rejected(self):
        rehearse_decision(self.db)
        with self.assertRaises(ContractError):
            rehearse_decision(self.db, action='REJECT')

    def test_injected_failures_roll_back_everything(self):
        for phase in ('decision', 'outbox', 'audit'):
            with self.subTest(phase=phase):
                with self.assertRaises(RuntimeError):
                    rehearse_decision(self.db, fail_at=phase)
                self.assertEqual(inventory(self.db), {'trial_decisions': 0, 'cancellation_jobs': 0, 'integration_audit': 0})

    def test_recovery_after_rollback(self):
        with self.assertRaises(RuntimeError):
            rehearse_decision(self.db, fail_at='outbox')
        rehearse_decision(self.db)
        self.assertEqual(inventory(self.db)['cancellation_jobs'], 2)

    def test_revoked_binding_blocks(self):
        self.db.execute("UPDATE identity_bindings SET state='REVOKED' WHERE id=9201")
        self.db.commit()
        with self.assertRaises(ContractError):
            rehearse_decision(self.db)
        self.assertEqual(inventory(self.db)['trial_decisions'], 0)

    def test_revoked_mapping_blocks(self):
        self.db.execute("UPDATE mapping_approvals SET state='REVOKED' WHERE id=9301")
        self.db.commit()
        with self.assertRaises(ContractError):
            rehearse_decision(self.db)

    def test_fk_rejects_unknown_attempt(self):
        with self.assertRaises(sqlite3.IntegrityError):
            with self.db:
                self.db.execute("INSERT INTO trial_decisions(id,series_id,approval_id,action,actor) VALUES(1,9001,9301,'KEEP','fixture')")
                self.db.execute("INSERT INTO cancellation_jobs(decision_id,attempt_id,torrent_hash) VALUES(1,999999,?)", ('f'*40,))
        self.assertEqual(inventory(self.db)['trial_decisions'], 0)

    def test_audit_immutable(self):
        rehearse_decision(self.db)
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM integration_audit")
        self.db.rollback()

    def test_file_backed_db_refused(self):
        # No file is created: a named shared-memory DB has a nonempty PRAGMA path on some builds,
        # so instead attach a second in-memory database and require_memory must refuse it.
        self.db.execute("ATTACH DATABASE ':memory:' AS extra")
        with self.assertRaises(ContractError):
            require_memory(self.db)

    def test_production_status_not_changed(self):
        rehearse_decision(self.db)
        self.assertEqual(self.db.execute('SELECT status FROM series WHERE id=9001').fetchone()[0], 'PENDING_REVIEW')

    def test_schema_approval_entry_bootstrap_gap(self):
        # Current AA schema blocks inserting entries after approval, but has no PENDING state.
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('INSERT INTO mapping_entries(approval_id,release_episode,season,episode) VALUES(9301,1,1,1)')
        self.db.rollback()

    def test_integrity(self):
        rehearse_decision(self.db)
        self.assertEqual(self.db.execute('PRAGMA quick_check').fetchone()[0], 'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(), [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
