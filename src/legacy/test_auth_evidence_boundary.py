import unittest
from pathlib import Path
from approval_authorization import sign_admin_request, AuthorizationError
from integration_transaction_rehearsal import build_fixture, ContractError
from mapping_lifecycle_rehearsal import install as install_mapping, create_draft, add_entry, approve
from auth_evidence_boundary import install, revoke_authenticated, approve_mapping

INSPECTION=Path(__file__).with_name('anime-integration-inspection.txt')
KEY=b'A'*32
NOW=1792038645

class BoundaryTests(unittest.TestCase):
    def setUp(self):
        self.db=build_fixture(INSPECTION.read_text())
        install_mapping(self.db); install(self.db)
        self.d=create_draft(self.db,series_id=9001,binding_id=9201,revision=2,evidence_digest='e'*64,actor='fixture')
        add_entry(self.db,self.d,27,1)
        approve(self.db,self.d,actor='fixture',trusted_evidence_verified=True) # pre-existing synthetic fixture only
    def tearDown(self): self.db.close()
    def envelope(self,nonce='n'*20,action='REVOKE_MAPPING',key=KEY):
        return sign_admin_request(key=key,action=action,actor='test-admin',nonce=nonce,
            issued_at=NOW-20,expires_at=NOW+100,target={'series_id':9001,'binding_id':9201,'candidate_sha256':'e'*64})
    def revoke(self,**kw):
        return revoke_authenticated(self.db,draft_id=self.d,envelope=self.envelope(),admin_key=KEY,now=NOW,**kw)
    def test_valid_revocation(self):
        self.assertEqual(self.revoke()['state'],'REVOKED')
        self.assertEqual(self.db.execute('SELECT count(*) FROM admin_nonces_v3').fetchone()[0],1)
    def test_replay_blocked(self):
        self.revoke()
        with self.assertRaises((ContractError,AuthorizationError)): self.revoke()
    def test_wrong_key(self):
        with self.assertRaises(AuthorizationError):
            revoke_authenticated(self.db,draft_id=self.d,envelope=self.envelope(),admin_key=b'B'*32,now=NOW)
    def test_wrong_action(self):
        with self.assertRaises(AuthorizationError):
            revoke_authenticated(self.db,draft_id=self.d,envelope=self.envelope(action='APPROVE_MAPPING'),admin_key=KEY,now=NOW)
    def test_expired(self):
        with self.assertRaises(AuthorizationError):
            revoke_authenticated(self.db,draft_id=self.d,envelope=self.envelope(),admin_key=KEY,now=NOW+200)
    def test_tampered_signature(self):
        e=self.envelope();e['payload']['actor']='other'
        with self.assertRaises(AuthorizationError):
            revoke_authenticated(self.db,draft_id=self.d,envelope=e,admin_key=KEY,now=NOW)
    def test_rollback(self):
        for step in ('nonce','state','audit'):
            with self.subTest(step=step):
                with self.assertRaises(RuntimeError): self.revoke(fail_at=step)
                self.assertEqual(self.db.execute('SELECT state FROM mapping_drafts_v2 WHERE id=?',(self.d,)).fetchone()[0],'APPROVED')
                self.assertEqual(self.db.execute('SELECT count(*) FROM admin_nonces_v3').fetchone()[0],0)
                self.assertEqual(self.db.execute('SELECT count(*) FROM admin_events_v3').fetchone()[0],0)
    def test_approval_disabled_even_with_flags(self):
        with self.assertRaises(ContractError):approve_mapping(trusted_evidence_verified=True,authenticated=True)
    def test_approval_disabled_without_flags(self):
        with self.assertRaises(ContractError):approve_mapping()
    def test_nonce_immutable(self):
        self.revoke()
        with self.assertRaises(Exception):self.db.execute('DELETE FROM admin_nonces_v3')
        self.db.rollback()
    def test_audit_immutable(self):
        self.revoke()
        with self.assertRaises(Exception):self.db.execute('UPDATE admin_events_v3 SET actor="changed"')
        self.db.rollback()
    def test_foreign_keys(self):
        self.revoke()
        self.assertEqual(self.db.execute('PRAGMA foreign_key_check').fetchall(),[])
    def test_no_production_file(self):
        self.assertEqual(self.db.execute('PRAGMA database_list').fetchone()[2],'')

if __name__=='__main__':unittest.main()
