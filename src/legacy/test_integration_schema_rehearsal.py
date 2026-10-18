import sqlite3
import unittest
from pathlib import Path
from integration_schema_rehearsal import make_rehearsal_database, extract_existing_schema

INSPECTION = Path(__file__).with_name('anime-integration-inspection.txt')

class IntegrationRehearsalTests(unittest.TestCase):
    def setUp(self):
        self.db = make_rehearsal_database(INSPECTION.read_text())
        self.db.execute("INSERT INTO series(id,source,external_id,title) VALUES (1,'test','TEST-001','Synthetic')")
    def tearDown(self): self.db.close()
    def test_original_tables(self):
        self.assertEqual(len(extract_existing_schema(INSPECTION.read_text())),5)
        self.assertEqual(self.db.execute('PRAGMA quick_check').fetchone()[0],'ok')
    def test_existing_status_enum_unchanged(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE series SET status='TRIAL' WHERE id=1")
    def test_foreign_key_enforced(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO identity_bindings(series_id,provider,provider_id,revision,state,evidence_digest,actor) VALUES (99,'anilist',11061,1,'ACTIVE',?, 'admin')",('a'*64,))
    def test_one_active_identity(self):
        self.db.execute("INSERT INTO identity_bindings(series_id,provider,provider_id,revision,state,evidence_digest,actor) VALUES (1,'anilist',11061,1,'ACTIVE',?,'admin')",('a'*64,))
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO identity_bindings(series_id,provider,provider_id,revision,state,evidence_digest,actor) VALUES (1,'anilist',11062,2,'ACTIVE',?,'admin')",('b'*64,))
    def test_mapping_constraints(self):
        self.db.execute("INSERT INTO identity_bindings(id,series_id,provider,provider_id,revision,state,evidence_digest,actor) VALUES (1,1,'anilist',11061,1,'ACTIVE',?,'admin')",('a'*64,))
        self.db.execute("INSERT INTO mapping_approvals(id,series_id,binding_id,revision,state,evidence_digest,actor) VALUES (1,1,1,1,'REVOKED',?,'admin')",('b'*64,))
        self.db.execute("INSERT INTO mapping_entries VALUES (1,27,1,3)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO mapping_entries VALUES (1,28,1,3)")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE mapping_entries SET episode=4 WHERE approval_id=1")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO mapping_entries VALUES (1,29,2,4)")
    def test_audit_immutable(self):
        self.db.execute("INSERT INTO integration_audit(event_type,series_id,detail) VALUES ('TEST',1,'dry-run')")
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("DELETE FROM integration_audit")
    def test_no_production_path_in_module(self):
        text=Path(__file__).with_name('integration_schema_rehearsal.py').read_text()
        self.assertNotIn('/var/lib/anime-discovery/controller.db',text)

if __name__ == '__main__': unittest.main(verbosity=2)
