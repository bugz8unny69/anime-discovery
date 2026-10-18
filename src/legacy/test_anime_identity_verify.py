import gzip
import unittest
from anime_identity_verify import anidb_titles, compare

class VerifierTests(unittest.TestCase):
    def test_official_index_shape(self):
        xml = b'<animetitles><anime aid="123"><title type="main">Solo Leveling</title><title type="syn">Ore dake Level Up na Ken</title></anime><anime aid="124"><title>Other</title></anime></animetitles>'
        self.assertEqual(anidb_titles(gzip.compress(xml), {'123'}), {'123': ['Ore dake Level Up na Ken', 'Solo Leveling']})
    def test_exact_alias(self):
        self.assertTrue(compare(['Solo Leveling'], {'titles': ['Solo-Leveling']})['title_overlap'])
    def test_different_titles(self):
        self.assertEqual(compare(['Solo Leveling'], {'titles': ['Bleach']})['status'], 'NEEDS_REVIEW')
    def test_no_titles(self):
        self.assertFalse(compare([], {'titles': ['Bleach']})['title_overlap'])

if __name__ == '__main__': unittest.main()
