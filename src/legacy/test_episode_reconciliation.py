"""Consolidated, offline phase 2X-K tests. No production side effects."""
import copy
import unittest
from episode_reconciliation import parse_release_number, reconcile, ReconciliationError

BINDING = dict(series_id=7, provider='anilist', provider_id=11061, state='ACTIVE', binding_id=44)
def sources(episode=27, canonical=3, season=None):
    entry = dict(release_season=season, release_episode=episode, canonical_season=1,
                 canonical_episode=canonical, kind='REGULAR')
    return [dict(provider=p, series_id=7, anilist_id=11061, entries=[copy.deepcopy(entry)])
            for p in ('sonarr', 'anidb')]
def run(title='[Group] Hunter x Hunter - 27 [1080p].mkv', binding=None, evidence=None):
    return reconcile(release_title=title, series_id=7, anilist_id=11061,
                     binding=BINDING if binding is None else binding,
                     episode_evidence=sources() if evidence is None else evidence)

class ReconciliationTests(unittest.TestCase):
    def reject(self, reason, **kw):
        with self.assertRaisesRegex(ReconciliationError, reason):
            run(**kw)
    def test_absolute_27_maps_to_3(self):
        result = run()
        self.assertEqual((result['release_episode'], result['canonical_season'], result['canonical_episode']), (27,1,3))
        self.assertFalse(result['canonical_mapping_authorized'])
    def test_standard_3(self):
        self.assertEqual(run(title='[G] Hunter - 03.mkv', evidence=sources(3))['canonical_episode'],3)
    def test_explicit_season_episode(self):
        self.assertEqual(run(title='Hunter S01E03.mkv', evidence=sources(3,season=1))['canonical_episode'],3)
    def test_explicit_season_mismatch(self): self.reject('MAPPING_NOT_FOUND', title='Hunter S02E03.mkv', evidence=sources(3,season=1))
    def test_no_implicit_season_inference(self): self.reject('MAPPING_NOT_FOUND', title='Hunter - 03.mkv', evidence=sources(3,season=1))
    def test_range(self): self.reject('MULTI_EPISODE', title='Hunter - 03-04.mkv')
    def test_multi_identifier(self): self.reject('AMBIGUOUS', title='Hunter - 03 EP04.mkv')
    def test_ova(self): self.reject('SPECIAL', title='Hunter OVA - 27.mkv')
    def test_recap(self): self.reject('SPECIAL', title='Hunter Recap - 27.mkv')
    def test_missing_number(self): self.reject('AMBIGUOUS', title='Hunter.mkv')
    def test_zero(self): self.reject('INVALID_NUMBER', title='Hunter - 00.mkv')
    def test_season_marker(self): self.reject('UNSUPPORTED_SEASON', title='Hunter Season 2 - 27.mkv')
    def test_binding_wrong_id(self): self.reject('IDENTITY_NOT_BOUND', binding={**BINDING,'provider_id':999})
    def test_revoked(self): self.reject('IDENTITY_NOT_BOUND', binding={**BINDING,'state':'REVOKED'})
    def test_missing_binding_id(self): self.reject('IDENTITY_NOT_BOUND', binding={**BINDING,'binding_id':None})
    def test_single_source(self): self.reject('TWO_SOURCES', evidence=sources()[:1])
    def test_duplicate_sources(self):
        e=sources(); e[1]['provider']='sonarr'; self.reject('INDEPENDENT', evidence=e)
    def test_identity_mismatch(self):
        e=sources(); e[1]['anilist_id']=999; self.reject('EVIDENCE_IDENTITY', evidence=e)
    def test_missing_mapping(self):
        e=sources(26); self.reject('MAPPING_NOT_FOUND', evidence=e)
    def test_conflicting_sources(self):
        e=sources(); e[1]['entries'][0]['canonical_episode']=4; self.reject('SOURCE_MAPPING_CONFLICT', evidence=e)
    def test_special_metadata(self):
        e=sources(); e[0]['entries'][0]['kind']='SPECIAL'; self.reject('NON_REGULAR', evidence=e)
    def test_outside_window(self): self.reject('OUTSIDE_TRIAL_WINDOW', evidence=sources(canonical=7))
    def test_wrong_canonical_season(self):
        e=sources();
        for x in e: x['entries'][0]['canonical_season']=2
        self.reject('OUTSIDE_TRIAL_WINDOW', evidence=e)
    def test_duplicate_release_entries(self):
        e=sources(); e[0]['entries'].append(copy.deepcopy(e[0]['entries'][0])); self.reject('CONFLICTING_EPISODE', evidence=e)
    def test_duplicate_canonical_entries(self):
        e=sources(); extra=copy.deepcopy(e[0]['entries'][0]); extra['release_episode']=28; e[0]['entries'].append(extra)
        self.reject('CONFLICTING_EPISODE', evidence=e)
    def test_invalid_boolean_number(self):
        e=sources(); e[0]['entries'][0]['release_episode']=True; self.reject('INVALID_EPISODE', evidence=e)
    def test_bad_entry_kind(self):
        e=sources(); e[0]['entries'][0]['kind']='OVA'; self.reject('NON_REGULAR', evidence=e)
    def test_empty_evidence(self): self.reject('MISSING_EPISODE_EVIDENCE', evidence=[{**sources()[0],'entries':[]},sources()[1]])

if __name__ == '__main__':
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(ReconciliationTests)
    result=unittest.TextTestRunner(verbosity=1).run(suite)
    if not result.wasSuccessful(): raise SystemExit(1)
    print(f'All {result.testsRun} offline episode reconciliation tests passed.')
