"""One-run offline regression suite; never opens the production database."""
import sqlite3
import unittest
from identity_binding import initialize, bind, revoke, lookup

class IdentityBindingTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        initialize(self.db)
        self.db.executemany('INSERT INTO series VALUES (?,?,?,?)', [
            (1,'test','TEST-001','Test anime'),
            (2,'test','TEST-002','Another anime')])
        self.db.commit()

    def tearDown(self):
        self.db.close()

    def add(self, series=1, provider=11061):
        return bind(self.db,series_id=series,provider_id=provider,
                    actor='offline-admin-fixture',evidence_ref='fixture:11061')

    def test_01_binding(self):
        bid=self.add(); self.assertEqual(lookup(self.db,1),('anilist',11061,bid))
    def test_02_no_title_lookup(self):
        self.assertIsNone(lookup(self.db,2))
    def test_03_duplicate_series_blocked(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.add(provider=999)
    def test_04_duplicate_provider_blocked(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.add(series=2)
    def test_05_invalid_provider_zero(self):
        with self.assertRaises(ValueError): self.add(provider=0)
    def test_06_invalid_provider_boolean(self):
        with self.assertRaises(ValueError): self.add(provider=True)
    def test_07_missing_series(self):
        with self.assertRaises(ValueError): self.add(series=99)
    def test_08_missing_actor(self):
        with self.assertRaises(ValueError):
            bind(self.db,series_id=1,provider_id=11061,actor='',evidence_ref='x')
    def test_09_missing_evidence(self):
        with self.assertRaises(ValueError):
            bind(self.db,series_id=1,provider_id=11061,actor='admin',evidence_ref=' ')
    def test_10_binding_audit(self):
        bid=self.add()
        self.assertEqual(self.db.execute('SELECT action,binding_id FROM identity_audit').fetchall(),[('BIND',bid)])
    def test_11_revoke(self):
        bid=self.add(); revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:1')
        self.assertIsNone(lookup(self.db,1))
    def test_12_revocation_audit(self):
        bid=self.add(); revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:1')
        self.assertEqual([r[0] for r in self.db.execute('SELECT action FROM identity_audit')],['BIND','REVOKE'])
    def test_13_no_double_revoke(self):
        bid=self.add(); revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:1')
        with self.assertRaises(ValueError): revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:2')
    def test_14_rebind_after_revoke(self):
        bid=self.add(); revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:1')
        next_id=self.add(provider=999)
        self.assertNotEqual(bid,next_id)
        self.assertEqual(lookup(self.db,1)[1],999)
    def test_15_history_retained(self):
        bid=self.add(); revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:1')
        self.assertEqual(self.db.execute('SELECT state FROM identity_bindings WHERE id=?',(bid,)).fetchone(),('REVOKED',))
    def test_16_no_binding_delete(self):
        bid=self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM identity_bindings WHERE id=?',(bid,))
    def test_17_no_binding_identity_rewrite(self):
        bid=self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('UPDATE identity_bindings SET provider_id=999 WHERE id=?',(bid,))
    def test_18_no_audit_edit(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE identity_audit SET actor='fake'")
    def test_19_no_audit_delete(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM identity_audit')
    def test_20_rejected_bind_no_audit(self):
        self.add()
        with self.assertRaises(sqlite3.IntegrityError): self.add(provider=999)
        self.assertEqual(self.db.execute('SELECT count(*) FROM identity_audit').fetchone()[0],1)
    def test_21_no_unrelated_changes(self):
        self.add(); self.assertEqual(self.db.execute('SELECT count(*) FROM series').fetchone()[0],2)
    def test_22_cannot_reactivate(self):
        bid=self.add(); revoke(self.db,binding_id=bid,actor='admin',evidence_ref='case:1')
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE identity_bindings SET state='ACTIVE',revoked_at=NULL WHERE id=?",(bid,))

if __name__=='__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(IdentityBindingTests)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if result.wasSuccessful(): print('All 22 offline identity-binding tests passed.')
    else: raise SystemExit(1)
