import sqlite3
import unittest
from pathlib import Path
from production_copy_migration_rehearsal import (REQUIRED,NEW,RehearsalError,integrity,
    migrate,rollback,rehearse,snapshot,tables)
from integration_schema_rehearsal import extract_existing_schema

INSPECTION=Path(__file__).with_name('anime-integration-inspection.txt')

def fixture():
    db=sqlite3.connect(':memory:')
    db.execute('PRAGMA foreign_keys=ON')
    for statement in extract_existing_schema(INSPECTION.read_text()):
        db.execute(statement)
    return db

class MigrationTests(unittest.TestCase):
    def setUp(self): self.db=fixture()
    def tearDown(self): self.db.close()
    def test_base_schema(self): self.assertTrue(REQUIRED.issubset(tables(self.db)))
    def test_integrity(self): self.assertTrue(integrity(self.db))
    def test_snapshot(self): self.assertEqual(set(snapshot(self.db)),REQUIRED)
    def test_migrate(self): self.assertEqual(migrate(self.db),'APPLIED')
    def test_tables(self):
        migrate(self.db); self.assertTrue(NEW.issubset(tables(self.db)))
    def test_idempotent(self):
        migrate(self.db); self.assertEqual(migrate(self.db),'ALREADY_APPLIED')
    def test_journal(self):
        migrate(self.db); self.assertEqual(self.db.execute('select version from an_migration_journal').fetchone()[0],1)
    def test_data_unchanged(self):
        before=snapshot(self.db); migrate(self.db); self.assertEqual(before,snapshot(self.db))
    def test_rollback(self):
        migrate(self.db); rollback(self.db); self.assertFalse(NEW.intersection(tables(self.db)))
    def test_rollback_without_migration(self):
        with self.assertRaises(RehearsalError): rollback(self.db)
    def test_failure_first(self):
        with self.assertRaises(RehearsalError): migrate(self.db,fail_at=0)
        self.assertFalse(NEW.intersection(tables(self.db)))
    def test_failure_second(self):
        with self.assertRaises(RehearsalError): migrate(self.db,fail_at=1)
        self.assertFalse(NEW.intersection(tables(self.db)))
    def test_failure_third(self):
        with self.assertRaises(RehearsalError): migrate(self.db,fail_at=2)
        self.assertFalse(NEW.intersection(tables(self.db)))
    def test_rehearsal(self): self.assertTrue(rehearse(self.db)['rollback_verified'])
    def test_not_production_ready(self): self.assertFalse(rehearse(self.db)['production_ready'])
    def test_partial_migration(self):
        self.db.execute('CREATE TABLE an_trial_decisions(x INTEGER)')
        with self.assertRaises(RehearsalError): migrate(self.db)
    def test_missing_schema(self):
        self.db.execute('DROP TABLE file_observations')
        with self.assertRaises(RehearsalError): migrate(self.db)
    def test_reject_nonempty_rollback(self):
        migrate(self.db)
        # Simulate business records in an outbox table; rollback must refuse.
        self.db.execute('PRAGMA foreign_keys=OFF')
        self.db.execute("INSERT INTO an_cancellation_outbox(series_id,attempt_id,torrent_hash,generation) VALUES(1,1,'abc',1)")
        with self.assertRaises(RehearsalError): rollback(self.db)
    def test_integrity_after_migration(self):
        migrate(self.db); self.assertTrue(integrity(self.db))
    def test_integrity_after_rollback(self):
        migrate(self.db); rollback(self.db); self.assertTrue(integrity(self.db))

if __name__=='__main__': unittest.main()
