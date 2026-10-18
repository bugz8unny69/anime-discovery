import copy
import hashlib
import sqlite3
import time
import unittest
from approval_authorization import candidate_digest, sign_admin_request
from transactional_approval import initialize as init_approval, approve_revision
from trusted_evidence import initialize, pin, preflight, EvidenceError

NOW=1800000000
KEY=b'z'*32

def fixture():
    candidate=dict(status='CANDIDATE_ONLY',canonical_mapping_authorized=False,series_id=1,
        anilist_id=11061,binding_id=1,release_episode=27,release_season=None,
        canonical_season=1,canonical_episode=3,sources=['anidb','sonarr'])
    evidence={'binding':{'binding_id':1,'series_id':1,'anilist_id':11061,'state':'ACTIVE'},'snapshots':[]}
    for p in ('anidb','sonarr'):
        evidence['snapshots'].append(dict(provider=p,series_id=1,anilist_id=11061,
            binding_id=1,release_episode=27,release_season=None,canonical_season=1,
            canonical_episode=3,kind='REGULAR',source_record_id=p+':123',retrieved_at=NOW-30))
    return candidate,evidence

class Tests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        init_approval(self.db)
        initialize(self.db)
        self.c,self.e=fixture()
        self.db.execute('INSERT INTO series VALUES (1)')
        self.db.execute("INSERT INTO identity_bindings VALUES (1,1,'ACTIVE')")
        self.db.execute('INSERT INTO mapping_revisions(id,series_id,binding_id,candidate_sha256) VALUES (1,1,1,?)',(candidate_digest(self.c),))
        self.db.execute('INSERT INTO mapping_entries VALUES (1,27,1,3)')
        self.db.commit()
    def tearDown(self): self.db.close()
    def pin(self): pin(self.db,revision_id=1,candidate=self.c,evidence=self.e,captured_at=NOW)
    def approve(self, nonce='A'*20, now=NOW):
        envelope=sign_admin_request(key=KEY,action='APPROVE_MAPPING',actor='admin',nonce=nonce,
            issued_at=now-5,expires_at=now+100,target={'series_id':1,'binding_id':1,'candidate_sha256':candidate_digest(self.c)})
        return approve_revision(self.db,revision_id=1,envelope=envelope,key=KEY,now=now,
            trusted_preflight=preflight)
    def test_success(self):
        self.pin(); self.assertEqual(self.approve()['status'],'APPROVED')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_nonces').fetchone()[0],1)
    def test_missing_pin(self):
        with self.assertRaises(EvidenceError): self.approve()
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM admin_nonces').fetchone()[0],0)
    def test_duplicate_pin(self):
        self.pin()
        with self.assertRaises(sqlite3.IntegrityError): self.pin()
    def test_immutable_update(self):
        self.pin()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute("UPDATE trusted_evidence SET evidence_json='x'")
    def test_immutable_delete(self):
        self.pin()
        with self.assertRaises(sqlite3.IntegrityError): self.db.execute('DELETE FROM trusted_evidence')
    def test_stale(self):
        self.pin()
        with self.assertRaises(EvidenceError): preflight(self.db,1,now=NOW+86401)
    def test_future(self):
        self.pin()
        with self.assertRaises(EvidenceError): preflight(self.db,1,now=NOW-1)
    def test_revoked(self):
        self.pin(); self.db.execute("UPDATE identity_bindings SET state='REVOKED'"); self.db.commit()
        with self.assertRaises(ValueError): self.approve()
    def test_wrong_mapping_entry(self):
        self.pin(); self.db.execute('UPDATE mapping_entries SET canonical_episode=2'); self.db.commit()
        with self.assertRaises(EvidenceError): self.approve()
    def test_extra_mapping_entry(self):
        self.pin(); self.db.execute('INSERT INTO mapping_entries VALUES (1,28,1,4)'); self.db.commit()
        with self.assertRaises(EvidenceError): self.approve()
    def test_mismatched_snapshot(self):
        self.e['snapshots'][0]['canonical_episode']=2
        with self.assertRaises(EvidenceError): self.pin()
    def test_duplicate_provider(self):
        self.e['snapshots'][1]['provider']='anidb'
        with self.assertRaises(EvidenceError): self.pin()
    def test_nonregular(self):
        self.e['snapshots'][0]['kind']='OVA'
        with self.assertRaises(EvidenceError): self.pin()
    def test_bad_binding(self):
        self.e['binding']['state']='REVOKED'
        with self.assertRaises(EvidenceError): self.pin()
    def test_bad_record_id(self):
        self.e['snapshots'][0]['source_record_id']=' '
        with self.assertRaises(EvidenceError): self.pin()
    def test_old_snapshot(self):
        self.e['snapshots'][0]['retrieved_at']=NOW-90000
        self.pin()
        with self.assertRaises(EvidenceError): self.approve()
    def test_future_snapshot(self):
        self.e['snapshots'][0]['retrieved_at']=NOW+1
        self.pin()
        with self.assertRaises(EvidenceError): self.approve()
    def test_revision_digest_mismatch(self):
        self.db.execute("UPDATE mapping_revisions SET candidate_sha256=? WHERE id=1",('0'*64,)); self.db.commit()
        with self.assertRaises(EvidenceError): self.pin()
    def test_no_approval_on_failure(self):
        self.pin(); self.db.execute('UPDATE mapping_entries SET canonical_episode=4'); self.db.commit()
        with self.assertRaises(EvidenceError): self.approve()
        self.assertEqual(self.db.execute('SELECT status FROM mapping_revisions').fetchone()[0],'PENDING')
        self.assertEqual(self.db.execute('SELECT COUNT(*) FROM mapping_audit').fetchone()[0],0)
    def test_replay(self):
        self.pin(); self.approve()
        with self.assertRaises(ValueError): self.approve()
    def test_candidate_not_authorized(self):
        self.c['canonical_mapping_authorized']=True
        with self.assertRaises(EvidenceError): self.pin()
    def test_missing_source(self):
        self.e['snapshots']=self.e['snapshots'][:1]
        with self.assertRaises(EvidenceError): self.pin()
    def test_bad_series(self):
        self.e['snapshots'][0]['series_id']=2
        with self.assertRaises(EvidenceError): self.pin()
    def test_stale_snapshot_boundary(self):
        self.e['snapshots'][0]['retrieved_at']=NOW-86400
        self.pin(); self.assertTrue(preflight(self.db,1,now=NOW))

if __name__=='__main__':
    unittest.main(verbosity=2)
