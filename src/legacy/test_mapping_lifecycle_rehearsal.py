import sqlite3
import unittest
from pathlib import Path
from integration_transaction_rehearsal import build_fixture, ContractError
from mapping_lifecycle_rehearsal import install,create_draft,add_entry,approve,revoke

INSPECTION=Path(__file__).with_name('anime-integration-inspection.txt')
class MappingLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.db=build_fixture(INSPECTION.read_text())
        install(self.db)
        self.d=create_draft(self.db,series_id=9001,binding_id=9201,revision=2,evidence_digest='e'*64,actor='fixture')
    def tearDown(self): self.db.close()
    def entries(self,*pairs):
        for r,e in pairs: add_entry(self.db,self.d,r,e)
    def seal(self,**kw): return approve(self.db,self.d,actor='admin-fixture',trusted_evidence_verified=True,**kw)
    def test_draft_creation(self): self.assertEqual(self.db.execute('SELECT state FROM mapping_drafts_v2').fetchone()[0],'DRAFT')
    def test_no_empty_approval(self):
        with self.assertRaises(ContractError): self.seal()
    def test_contiguous_prefix(self):
        self.entries((27,1),(28,2),(29,3)); self.seal()
        self.assertEqual(self.db.execute('SELECT state FROM mapping_drafts_v2').fetchone()[0],'APPROVED')
    def test_one_episode_allowed(self): self.entries((27,1)); self.seal()
    def test_gap_rejected(self):
        self.entries((27,1),(29,3))
        with self.assertRaises(ContractError): self.seal()
    def test_episode_two_only_rejected(self):
        self.entries((28,2))
        with self.assertRaises(ContractError): self.seal()
    def test_evidence_required(self):
        self.entries((27,1))
        with self.assertRaises(ContractError): approve(self.db,self.d,actor='admin')
    def test_no_edit_after_approval(self):
        self.entries((27,1));self.seal()
        with self.assertRaises(ContractError): add_entry(self.db,self.d,28,2)
    def test_no_delete_after_approval(self):
        self.entries((27,1));self.seal()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM mapping_draft_entries_v2')
        self.db.rollback()
    def test_revoke(self):
        self.entries((27,1));self.seal();revoke(self.db,self.d,actor='admin')
        self.assertEqual(self.db.execute('SELECT state FROM mapping_drafts_v2').fetchone()[0],'REVOKED')
    def test_no_double_revoke(self):
        self.entries((27,1));self.seal();revoke(self.db,self.d,actor='admin')
        with self.assertRaises(ContractError): revoke(self.db,self.d,actor='admin')
    def test_approval_rollback(self):
        self.entries((27,1))
        for step in ('seal','audit'):
            with self.subTest(step=step):
                with self.assertRaises(RuntimeError): self.seal(fail_at=step)
                self.assertEqual(self.db.execute('SELECT state FROM mapping_drafts_v2').fetchone()[0],'DRAFT')
                self.assertEqual(self.db.execute('SELECT count(*) FROM mapping_lifecycle_events_v2').fetchone()[0],0)
    def test_revoked_binding(self):
        self.entries((27,1));self.db.execute("UPDATE identity_bindings SET state='REVOKED' WHERE id=9201");self.db.commit()
        with self.assertRaises(ContractError): self.seal()
    def test_second_active_mapping_blocked(self):
        self.entries((27,1));self.seal()
        other=create_draft(self.db,series_id=9001,binding_id=9201,revision=3,evidence_digest='f'*64,actor='fixture')
        add_entry(self.db,other,28,1)
        with self.assertRaises(sqlite3.IntegrityError): approve(self.db,other,actor='admin',trusted_evidence_verified=True)
    def test_audit_immutable(self):
        self.entries((27,1));self.seal()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM mapping_lifecycle_events_v2')
        self.db.rollback()
    def test_no_mutation_existing_tables(self):
        self.entries((27,1));self.seal()
        self.assertEqual(self.db.execute('SELECT status FROM series WHERE id=9001').fetchone()[0],'PENDING_REVIEW')
        self.assertEqual(self.db.execute('SELECT state FROM mapping_approvals WHERE id=9301').fetchone()[0],'APPROVED')
    def test_integrity(self):
        self.entries((27,1));self.seal()
        self.assertEqual(self.db.execute('PRAGMA quick_check').fetchone()[0],'ok')
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
if __name__=='__main__': unittest.main()
