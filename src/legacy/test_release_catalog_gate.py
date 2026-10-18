import unittest
from release_catalog_gate import assess_release, ReleaseBlocked

CAT={'status':'CANDIDATE_ONLY','canonical_mapping_authorized':False,
     'prefix':[{'season':1,'episode':i,'sonarr_title':f'Title {i}', 'tvmaze_title':f'Title {i}'} for i in range(1,7)]}

def check(name='Solo Leveling S01E01', files=('Solo Leveling S01E01.mkv',), catalog=CAT, label='Solo Leveling'):
    return assess_release(catalog, release_name=name, file_names=files, expected_series_label=label)

class ReleaseGateTests(unittest.TestCase):
    def test_candidate(self):
        result=check()
        self.assertEqual((result.season,result.episode,result.status),(1,1,'CANDIDATE_ONLY'))
        self.assertFalse(result.canonical_mapping_authorized)
        self.assertFalse(result.release_mapping_verified)
        self.assertFalse(result.keep_or_reject_authorized)
    def test_episode_six(self):
        self.assertEqual(check('Solo Leveling S01E06',('Solo Leveling S01E06.mp4',)).episode,6)
    def test_mismatch(self):
        with self.assertRaises(ReleaseBlocked): check(files=('Solo Leveling S01E02.mkv',))
    def test_other_series(self):
        with self.assertRaises(ReleaseBlocked): check('Other Anime S01E01')
    def test_file_other_series(self):
        with self.assertRaises(ReleaseBlocked): check(files=('Other Anime S01E01.mkv',))
    def test_batch(self):
        with self.assertRaises(ReleaseBlocked): check('Solo Leveling S01E01-06')
    def test_special(self):
        with self.assertRaises(ReleaseBlocked): check('Solo Leveling OVA - 01')
    def test_multiple_files(self):
        with self.assertRaises(ReleaseBlocked): check(files=('Solo Leveling S01E01.mkv','Solo Leveling S01E02.mkv'))
    def test_path_rejected(self):
        with self.assertRaises(ReleaseBlocked): check(files=('../Solo Leveling S01E01.mkv',))
    def test_extension(self):
        with self.assertRaises(ReleaseBlocked): check(files=('Solo Leveling S01E01.exe',))
    def test_bad_catalog(self):
        with self.assertRaises(ReleaseBlocked): check(catalog={**CAT,'status':'APPROVED'})
    def test_bad_catalog_gap(self):
        with self.assertRaises(ReleaseBlocked): check(catalog={**CAT,'prefix':[CAT['prefix'][1]]})
    def test_bad_catalog_title(self):
        rows=[dict(x) for x in CAT['prefix']];rows[0]['tvmaze_title']='Different'
        with self.assertRaises(ReleaseBlocked): check(catalog={**CAT,'prefix':rows})
    def test_episode_outside_prefix(self):
        with self.assertRaises(ReleaseBlocked): check('Solo Leveling S01E06',('Solo Leveling S01E06.mkv',),{**CAT,'prefix':CAT['prefix'][:3]})
    def test_no_file(self):
        with self.assertRaises(ReleaseBlocked): check(files=())
    def test_null(self):
        with self.assertRaises(ReleaseBlocked): check(name='Solo Leveling S01E01\x00')

if __name__=='__main__': unittest.main()
