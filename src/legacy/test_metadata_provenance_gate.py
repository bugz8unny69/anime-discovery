import unittest
from dataclasses import replace
from metadata_provenance_gate import (IdentityEvidence, EpisodeEvidence, evaluate,
    approve_automatically, approve_manually, ProvenanceError)

class MetadataProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.identity = IdentityEvidence(11061, 7, 55)
        self.s = EpisodeEvidence('sonarr',7,1,1,27,'REGULAR',1000,'s-1')
        self.a = EpisodeEvidence('anidb',55,1,1,27,'REGULAR',1000,'a-1')
    def check(self, reason, identity=None, records=None):
        result = evaluate(identity or self.identity,
                          [self.s,self.a] if records is None else records,now=1000)
        self.assertEqual(result.status,'BLOCKED')
        self.assertIn(reason,result.reasons)
        self.assertFalse(result.automatic_approval_authorized)
        self.assertFalse(result.manual_approval_authorized)
    def test_unattested_crossref(self): self.check('CROSS_REFERENCE_NOT_ATTESTED')
    def test_missing_source(self): self.check('TWO_SOURCE_RECORDS_REQUIRED',records=[self.s])
    def test_same_source_twice(self): self.check('INDEPENDENT_PROVIDERS_REQUIRED',records=[self.s,self.s])
    def test_numbering_conflict(self): self.check('NUMBERING_CONFLICT',records=[self.s,replace(self.a,release_episode=28)])
    def test_wrong_series(self): self.check('SERIES_ID_MISMATCH',records=[self.s,replace(self.a,provider_series_id=99)])
    def test_special_blocked(self): self.check('INVALID_EPISODE_RECORD',records=[self.s,replace(self.a,kind='SPECIAL')])
    def test_season_two_blocked(self): self.check('INVALID_EPISODE_RECORD',records=[replace(self.s,canonical_season=2),self.a])
    def test_episode_seven_blocked(self): self.check('INVALID_EPISODE_RECORD',records=[replace(self.s,canonical_episode=7),self.a])
    def test_future_record(self): self.check('STALE_OR_FUTURE_RECORD',records=[self.s,replace(self.a,observed_at=1001)])
    def test_stale_record(self):
        result = evaluate(self.identity, [self.s, replace(self.a, observed_at=1)], now=100000, max_age=500)
        self.assertIn('STALE_OR_FUTURE_RECORD', result.reasons)
    def test_self_asserted_trust_not_sufficient(self):
        r=evaluate(replace(self.identity,cross_reference_attested=True),
          [replace(self.s,authenticated_transport=True,source_attested=True),
           replace(self.a,authenticated_transport=True,source_attested=True)],now=1000)
        self.assertEqual(r.reasons,('PRODUCTION_TRUST_GATE_NOT_IMPLEMENTED',))
        self.assertFalse(r.automatic_approval_authorized)
    def test_candidate_only(self): self.assertEqual(evaluate(self.identity,[self.s,self.a],now=1000).candidate,(27,1,1))
    def test_auto_approval_unavailable(self):
        with self.assertRaises(ProvenanceError): approve_automatically()
    def test_manual_approval_unavailable(self):
        with self.assertRaises(ProvenanceError): approve_manually()
    def test_invalid_clock(self):
        with self.assertRaises(ProvenanceError): evaluate(self.identity,[self.s,self.a],now=True)
    def test_invalid_ids(self):
        with self.assertRaises(ProvenanceError): evaluate(replace(self.identity,anilist_id=0),[self.s,self.a],now=1000)

if __name__=='__main__': unittest.main()
