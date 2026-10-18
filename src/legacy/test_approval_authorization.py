import copy
import hashlib
import unittest
from approval_authorization import (AuthorizationError, candidate_digest,
    sign_admin_request, verify_admin_request)

KEY = b'A' * 32
TARGET = {'series_id': 7, 'binding_id': 12, 'candidate_sha256': 'a' * 64}

def envelope(**kw):
    d = dict(key=KEY, action='APPROVE_MAPPING', actor='local-admin',
             nonce='nonce0123456789abcdef', issued_at=1000, expires_at=1100,
             target=TARGET)
    d.update(kw)
    return sign_admin_request(**d)

def verify(e, **kw):
    d = dict(envelope=e, key=KEY, expected_action='APPROVE_MAPPING',
             expected_target=TARGET, nonce_is_used=lambda n: False, now=1050)
    d.update(kw)
    return verify_admin_request(**d)

class Tests(unittest.TestCase):
    def test_valid(self): self.assertEqual(verify(envelope())['actor'], 'local-admin')
    def test_deterministic_signature(self): self.assertEqual(envelope(), envelope())
    def test_other_key(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), key=b'B'*32)
    def test_weak_key_sign(self):
        with self.assertRaises(AuthorizationError): envelope(key=b'weak')
    def test_weak_key_verify(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), key=b'weak')
    def test_changed_actor(self):
        e=envelope(); e['payload']['actor']='attacker'
        with self.assertRaises(AuthorizationError): verify(e)
    def test_changed_target(self):
        e=envelope(); e['payload']['target']['series_id']=8
        with self.assertRaises(AuthorizationError): verify(e)
    def test_changed_action(self):
        e=envelope(); e['payload']['action']='REVOKE_MAPPING'
        with self.assertRaises(AuthorizationError): verify(e)
    def test_expected_action(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), expected_action='REVOKE_MAPPING')
    def test_expected_target(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), expected_target={**TARGET, 'series_id':8})
    def test_expired(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), now=1100)
    def test_not_yet(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), now=969)
    def test_clock_skew(self): self.assertTrue(verify(envelope(), now=970))
    def test_replay(self):
        with self.assertRaises(AuthorizationError): verify(envelope(), nonce_is_used=lambda n: True)
    def test_invalid_nonce(self):
        with self.assertRaises(AuthorizationError): envelope(nonce='short')
    def test_invalid_actor(self):
        with self.assertRaises(AuthorizationError): envelope(actor='')
    def test_invalid_action(self):
        with self.assertRaises(AuthorizationError): envelope(action='DOWNLOAD')
    def test_long_lifetime(self):
        with self.assertRaises(AuthorizationError): envelope(expires_at=1400)
    def test_bool_timestamp(self):
        with self.assertRaises(AuthorizationError): envelope(issued_at=True)
    def test_invalid_target(self):
        with self.assertRaises(AuthorizationError): envelope(target={**TARGET, 'series_id':True})
    def test_invalid_signature(self):
        e=envelope(); e['signature']='0'*64
        with self.assertRaises(AuthorizationError): verify(e)
    def test_extra_envelope_fields(self):
        e=envelope(); e['approved']=True
        with self.assertRaises(AuthorizationError): verify(e)
    def test_candidate_digest(self):
        c={'status':'CANDIDATE_ONLY','canonical_mapping_authorized':False,
           'series_id':7,'anilist_id':11061,'binding_id':12,'release_episode':3,
           'canonical_season':1,'canonical_episode':3,'sources':['anidb','sonarr']}
        self.assertEqual(len(candidate_digest(c)),64)
        self.assertNotEqual(candidate_digest(c),candidate_digest({**c,'release_episode':4}))
    def test_candidate_wrong_sources(self):
        c={'status':'CANDIDATE_ONLY','canonical_mapping_authorized':False,
           'series_id':7,'anilist_id':11061,'binding_id':12,'release_episode':3,
           'canonical_season':1,'canonical_episode':3,'sources':['sonarr']}
        with self.assertRaises(AuthorizationError): candidate_digest(c)
    def test_candidate_outside_window(self):
        c={'status':'CANDIDATE_ONLY','canonical_mapping_authorized':False,
           'series_id':7,'anilist_id':11061,'binding_id':12,'release_episode':3,
           'canonical_season':1,'canonical_episode':7,'sources':['anidb','sonarr']}
        with self.assertRaises(AuthorizationError): candidate_digest(c)

if __name__ == '__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Tests)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)
    print(f'All {result.testsRun} offline authorization tests passed.')
