"""One consolidated, disposable-SQLite regression run for Phase 2X-Q."""
import os
import sqlite3
import tempfile
import unittest
from approval_authorization import candidate_digest, sign_admin_request
from approval_gateway import approve_pinned_revision, GatewayError
from transactional_approval import initialize as init_approval
from trusted_evidence import initialize as init_evidence, pin, EvidenceError

NOW = 1800000000
KEY = b'Q' * 32

def fixture():
    candidate = dict(status='CANDIDATE_ONLY', canonical_mapping_authorized=False,
        series_id=1, anilist_id=11061, binding_id=1, release_episode=27,
        release_season=None, canonical_season=1, canonical_episode=3,
        sources=['anidb', 'sonarr'])
    evidence = {'binding': {'binding_id':1,'series_id':1,'anilist_id':11061,'state':'ACTIVE'},
                'snapshots': []}
    for provider in ('anidb', 'sonarr'):
        evidence['snapshots'].append(dict(provider=provider, series_id=1,
            anilist_id=11061, binding_id=1, release_episode=27,
            release_season=None, canonical_season=1, canonical_episode=3,
            kind='REGULAR', source_record_id=provider+':123', retrieved_at=NOW-30))
    return candidate, evidence

class GatewayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, 'test.db')
        self.db = sqlite3.connect(self.path, timeout=2)
        self.db.execute('PRAGMA foreign_keys=ON')
        init_approval(self.db)
        init_evidence(self.db)
        self.c, self.e = fixture()
        self.db.execute('INSERT INTO series VALUES (1)')
        self.db.execute("INSERT INTO identity_bindings VALUES (1,1,'ACTIVE')")
        self.db.execute('INSERT INTO mapping_revisions(id,series_id,binding_id,candidate_sha256) VALUES (1,1,1,?)', (candidate_digest(self.c),))
        self.db.execute('INSERT INTO mapping_entries VALUES (1,27,1,3)')
        self.db.commit()
    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()
    def envelope(self, nonce='A'*20, target=None):
        return sign_admin_request(key=KEY, action='APPROVE_MAPPING', actor='admin',
            nonce=nonce, issued_at=NOW-5, expires_at=NOW+100,
            target=target or {'series_id':1,'binding_id':1,'candidate_sha256':candidate_digest(self.c)})
    def approve(self, **kwargs):
        return approve_pinned_revision(self.db, revision_id=1,
            envelope=self.envelope(), admin_key=KEY, now=NOW, **kwargs)
    def pin(self, captured_at=NOW):
        pin(self.db, revision_id=1, candidate=self.c, evidence=self.e, captured_at=captured_at)
    def counts(self):
        return tuple(self.db.execute('SELECT COUNT(*) FROM '+t).fetchone()[0]
                     for t in ('admin_nonces','mapping_audit'))
    def test_happy_path_persists_after_reopen(self):
        self.pin()
        self.assertEqual(self.approve()['status'], 'APPROVED')
        self.assertEqual(self.counts(), (1,1))
        self.db.close()
        self.db = sqlite3.connect(self.path)
        self.assertEqual(self.db.execute('SELECT status FROM mapping_revisions').fetchone()[0], 'APPROVED')
        self.assertEqual(self.counts(), (1,1))
    def test_missing_evidence_fails_closed(self):
        with self.assertRaises(EvidenceError): self.approve()
        self.assertEqual(self.counts(), (0,0))
    def test_stale_evidence_fails_closed(self):
        self.pin(captured_at=NOW-86401)
        with self.assertRaises(EvidenceError): self.approve()
        self.assertEqual(self.counts(), (0,0))
    def test_wrong_mapping_fails_closed(self):
        self.pin()
        self.db.execute('UPDATE mapping_entries SET canonical_episode=4')
        self.db.commit()
        with self.assertRaises(EvidenceError): self.approve()
        self.assertEqual(self.counts(), (0,0))
    def test_revoked_binding_fails_closed(self):
        self.pin()
        self.db.execute("UPDATE identity_bindings SET state='REVOKED'")
        self.db.commit()
        with self.assertRaises(ValueError): self.approve()
        self.assertEqual(self.counts(), (0,0))
    def test_invalid_signature_rollback(self):
        self.pin()
        bad = self.envelope()
        bad['signature'] = '0'*64
        with self.assertRaises(ValueError):
            approve_pinned_revision(self.db, revision_id=1, envelope=bad, admin_key=KEY, now=NOW)
        self.assertEqual(self.counts(), (0,0))
    def test_wrong_target_rollback(self):
        self.pin()
        bad = self.envelope(target={'series_id':1,'binding_id':1,'candidate_sha256':'0'*64})
        with self.assertRaises(ValueError):
            approve_pinned_revision(self.db, revision_id=1, envelope=bad, admin_key=KEY, now=NOW)
        self.assertEqual(self.counts(), (0,0))
    def test_duplicate_approval_fails(self):
        self.pin()
        self.approve()
        with self.assertRaises(ValueError): self.approve()
        self.assertEqual(self.counts(), (1,1))
    def test_no_preflight_override(self):
        self.pin()
        with self.assertRaises(TypeError): self.approve(trusted_preflight=None)
        self.assertEqual(self.counts(), (0,0))
    def test_no_candidate_override(self):
        self.pin()
        with self.assertRaises(TypeError): self.approve(candidate=self.c)
        self.assertEqual(self.counts(), (0,0))
    def test_reject_invalid_arguments(self):
        for args in [dict(revision_id=0,envelope=self.envelope(),admin_key=KEY,now=NOW),
                     dict(revision_id=True,envelope=self.envelope(),admin_key=KEY,now=NOW),
                     dict(revision_id=1,envelope=None,admin_key=KEY,now=NOW),
                     dict(revision_id=1,envelope=self.envelope(),admin_key=b'x',now=NOW),
                     dict(revision_id=1,envelope=self.envelope(),admin_key=KEY,now=True)]:
            with self.subTest(args=args), self.assertRaises(GatewayError):
                approve_pinned_revision(self.db, **args)
    def test_no_implicit_transaction_leak(self):
        with self.assertRaises(EvidenceError): self.approve()
        self.assertFalse(self.db.in_transaction)
    def test_separate_connection_sees_no_failed_approval(self):
        with self.assertRaises(EvidenceError): self.approve()
        other=sqlite3.connect(self.path)
        try:
            self.assertEqual(other.execute('SELECT status FROM mapping_revisions').fetchone()[0], 'PENDING')
            self.assertEqual(other.execute('SELECT COUNT(*) FROM admin_nonces').fetchone()[0], 0)
        finally: other.close()

if __name__ == '__main__':
    unittest.main(verbosity=2)
