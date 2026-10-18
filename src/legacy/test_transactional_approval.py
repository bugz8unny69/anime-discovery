"""Consolidated offline test; never touches the live controller database."""
import os
import sqlite3
import tempfile
import unittest
from approval_authorization import sign_admin_request, AuthorizationError
from transactional_approval import initialize, approve_revision

KEY = b'admin-key-for-offline-tests-only-1234567890'
DIGEST = 'a' * 64
NOW = 1_800_000_000


def envelope(*, nonce='nonce00000000000001', action='APPROVE_MAPPING',
             series=7, binding=9, digest=DIGEST, actor='admin'):
    return sign_admin_request(key=KEY, action=action, actor=actor, nonce=nonce,
        issued_at=NOW-10, expires_at=NOW+100,
        target={'series_id':series,'binding_id':binding,'candidate_sha256':digest})


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'offline.sqlite')
        self.db = sqlite3.connect(self.path, isolation_level=None, timeout=1)
        initialize(self.db)
        self.db.execute('INSERT INTO series VALUES (7)')
        self.db.execute("INSERT INTO identity_bindings VALUES (9,7,'ACTIVE')")
        self.db.execute('INSERT INTO mapping_revisions(id,series_id,binding_id,candidate_sha256) VALUES (11,7,9,?)', (DIGEST,))
        self.db.execute('INSERT INTO mapping_entries VALUES (11,1,1,1)')

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def run_approval(self, env=None):
        return approve_revision(self.db, revision_id=11,
                                envelope=envelope() if env is None else env,
                                key=KEY, now=NOW)

    def counts(self):
        return tuple(self.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                     for t in ('admin_nonces','mapping_audit'))

    def test_success(self):
        self.assertEqual(self.run_approval()['status'], 'APPROVED')
        self.assertEqual(self.counts(), (1,1))

    def test_replay(self):
        self.run_approval()
        with self.assertRaises((ValueError, AuthorizationError)):
            self.run_approval()
        self.assertEqual(self.counts(), (1,1))

    def test_tampered_signature(self):
        e=envelope(); e['signature']='0'*64
        with self.assertRaises(AuthorizationError): self.run_approval(e)
        self.assertEqual(self.counts(), (0,0))

    def test_wrong_series(self):
        with self.assertRaises(AuthorizationError): self.run_approval(envelope(series=8))
        self.assertEqual(self.counts(), (0,0))

    def test_wrong_binding(self):
        with self.assertRaises(AuthorizationError): self.run_approval(envelope(binding=10))
        self.assertEqual(self.counts(), (0,0))

    def test_wrong_digest(self):
        with self.assertRaises(AuthorizationError): self.run_approval(envelope(digest='b'*64))
        self.assertEqual(self.counts(), (0,0))

    def test_wrong_action(self):
        with self.assertRaises(AuthorizationError): self.run_approval(envelope(action='REVOKE_MAPPING'))
        self.assertEqual(self.counts(), (0,0))

    def test_expired(self):
        with self.assertRaises(AuthorizationError):
            approve_revision(self.db,revision_id=11,envelope=envelope(),key=KEY,now=NOW+101)
        self.assertEqual(self.counts(), (0,0))

    def test_revoked_binding(self):
        self.db.execute("UPDATE identity_bindings SET state='REVOKED' WHERE id=9")
        with self.assertRaises(ValueError): self.run_approval()
        self.assertEqual(self.counts(), (0,0))

    def test_empty_mapping(self):
        self.db.execute('DELETE FROM mapping_entries WHERE revision_id=11')
        with self.assertRaises(ValueError): self.run_approval()
        self.assertEqual(self.counts(), (0,0))

    def test_rollback_on_audit_failure(self):
        self.db.execute('''CREATE TRIGGER block_audit BEFORE INSERT ON mapping_audit
          BEGIN SELECT RAISE(ABORT,'simulated audit failure'); END''')
        with self.assertRaises(sqlite3.IntegrityError): self.run_approval()
        self.assertEqual(self.counts(), (0,0))
        self.assertEqual(self.db.execute('SELECT status FROM mapping_revisions WHERE id=11').fetchone()[0], 'PENDING')

    def test_second_approved_revision_rolls_back(self):
        self.db.execute('INSERT INTO mapping_revisions(id,series_id,binding_id,candidate_sha256) VALUES (12,7,9,?)', (DIGEST,))
        self.db.execute('INSERT INTO mapping_entries VALUES (12,2,1,2)')
        self.run_approval()
        with self.assertRaises(sqlite3.IntegrityError):
            approve_revision(self.db,revision_id=12,envelope=envelope(nonce='nonce00000000000002'),key=KEY,now=NOW)
        self.assertEqual(self.counts(), (1,1))

    def test_persisted_nonce_survives_reopen(self):
        self.run_approval()
        self.db.close()
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.assertEqual(self.counts(), (1,1))

    def test_nonce_unique_constraint(self):
        self.run_approval()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("INSERT INTO admin_nonces VALUES ('nonce00000000000001','APPROVE_MAPPING','admin',11,CURRENT_TIMESTAMP)")

    def test_audit_immutable(self):
        self.run_approval()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE mapping_audit SET actor='other'")

    def test_nonce_immutable(self):
        self.run_approval()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('DELETE FROM admin_nonces')

    def test_entries_immutable_after_approval(self):
        self.run_approval()
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute('UPDATE mapping_entries SET canonical_episode=2 WHERE revision_id=11')

    def test_wrong_key(self):
        with self.assertRaises(AuthorizationError):
            approve_revision(self.db,revision_id=11,envelope=envelope(),key=b'z'*32,now=NOW)
        self.assertEqual(self.counts(), (0,0))

    def test_invalid_revision(self):
        with self.assertRaises(ValueError):
            approve_revision(self.db,revision_id=0,envelope=envelope(),key=KEY,now=NOW)

    def test_reject_nested_transaction(self):
        self.db.execute('BEGIN')
        try:
            with self.assertRaises(ValueError): self.run_approval()
        finally:
            self.db.rollback()

    def test_concurrent_same_nonce(self):
        other=sqlite3.connect(self.path,isolation_level=None,timeout=1)
        try:
            self.run_approval()
            with self.assertRaises((ValueError, AuthorizationError, sqlite3.IntegrityError)):
                approve_revision(other,revision_id=11,envelope=envelope(),key=KEY,now=NOW)
            self.assertEqual(self.counts(), (1,1))
        finally:
            other.close()


if __name__ == '__main__':
    unittest.main(verbosity=2)
