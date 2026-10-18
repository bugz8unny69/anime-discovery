import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock
from pilot_readiness import rehearse_restore, audit_series_mapping, audit_sonarr, ReadinessBlocked

class ReadinessTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db = Path(self.tmp.name) / 'source.db'
        with sqlite3.connect(self.db) as conn:
            conn.execute('CREATE TABLE series(id INTEGER PRIMARY KEY, title TEXT NOT NULL)')
            conn.execute('INSERT INTO series VALUES (1, ?)', ('sample',))
        self.series = {'id': 42, 'tvdbId': 12345, 'title': 'ignored'}
        self.episodes = [{'seasonNumber': 1, 'episodeNumber': n} for n in range(1, 9)]
    def test_restore_rehearsal(self):
        result = rehearse_restore(self.db, workdir=self.tmp.name)
        self.assertEqual(result['restore_rehearsal'], 'PASS')
        self.assertEqual(result['table_counts']['series'], 1)
        self.assertFalse(result['production_database_modified'])
    def test_original_unchanged(self):
        before = self.db.read_bytes()
        rehearse_restore(self.db, workdir=self.tmp.name)
        self.assertEqual(self.db.read_bytes(), before)
    def test_no_leftover_files(self):
        rehearse_restore(self.db, workdir=self.tmp.name)
        self.assertEqual([p.name for p in Path(self.tmp.name).iterdir()], ['source.db'])
    def test_mapping_not_approved(self):
        r = audit_series_mapping(self.series, self.episodes)
        self.assertEqual(r['contiguous_trial_prefix'], [1,2,3,4,5,6])
        self.assertFalse(r['canonical_mapping_approved'])
    def test_short_prefix(self):
        r = audit_series_mapping(self.series, self.episodes[:3])
        self.assertEqual(r['contiguous_trial_prefix'], [1,2,3])
    def test_missing_episode_one(self):
        with self.assertRaises(ReadinessBlocked):
            audit_series_mapping(self.series, self.episodes[1:])
    def test_duplicate_episode(self):
        with self.assertRaises(ReadinessBlocked):
            audit_series_mapping(self.series, self.episodes + [self.episodes[0]])
    def test_missing_tvdb(self):
        with self.assertRaises(ReadinessBlocked):
            audit_series_mapping({'id': 42}, self.episodes)
    def test_invalid_series_id(self):
        with self.assertRaises(ReadinessBlocked):
            audit_series_mapping({'id': True, 'tvdbId': 1}, self.episodes)
    def test_reject_invalid_number(self):
        with self.assertRaises(ReadinessBlocked):
            audit_series_mapping(self.series, [{'seasonNumber':1, 'episodeNumber':0}])
    def test_specials_not_trial(self):
        r = audit_series_mapping(self.series, [{'seasonNumber':0,'episodeNumber':1}]+self.episodes)
        self.assertEqual(r['contiguous_trial_prefix'], [1,2,3,4,5,6])
    def test_exact_id_audit(self):
        client = Mock()
        client.series.return_value = [self.series, {'id':43,'tvdbId':44}]
        client.episodes.return_value = self.episodes
        self.assertEqual(audit_sonarr(client, series_id=42)['tvdb_id'], 12345)
        client.episodes.assert_called_once_with(42)
    def test_no_title_guess(self):
        client = Mock()
        client.series.return_value = [{'id':43,'tvdbId':12345,'title':'ignored'}]
        with self.assertRaises(ReadinessBlocked):
            audit_sonarr(client, series_id=42)
        client.episodes.assert_not_called()
    def test_reject_invalid_audit_id(self):
        with self.assertRaises(ReadinessBlocked):
            audit_sonarr(Mock(), series_id=True)
    def test_empty_episodes(self):
        with self.assertRaises(ReadinessBlocked):
            audit_series_mapping(self.series, [])

if __name__ == '__main__': unittest.main()
