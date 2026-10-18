import os
import tempfile
import unittest
from pathlib import Path
from live_boundary_patch import (BoundaryError, fingerprint_regular_file,
    verify_unchanged, mapping_evidence_gate, guarded_cancel_decision)


class Boundaries(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'staging'
        self.root.mkdir()
        self.file = self.root / 'e1.mkv'
        self.file.write_bytes(b'video fixture')

    def test_fingerprint(self):
        self.assertEqual(len(fingerprint_regular_file(self.file, self.root)['sha256']), 64)

    def test_unchanged(self):
        fp = fingerprint_regular_file(self.file, self.root)
        self.assertTrue(verify_unchanged(self.file, self.root, fp))

    def test_modified(self):
        fp = fingerprint_regular_file(self.file, self.root)
        self.file.write_bytes(b'changed')
        self.assertFalse(verify_unchanged(self.file, self.root, fp))

    def test_replaced_same_content(self):
        fp = fingerprint_regular_file(self.file, self.root)
        self.file.unlink()
        self.file.write_bytes(b'video fixture')
        self.assertFalse(verify_unchanged(self.file, self.root, fp))

    def test_symlink(self):
        alias = self.root / 'alias.mkv'
        alias.symlink_to(self.file)
        with self.assertRaises((BoundaryError, OSError)):
            fingerprint_regular_file(alias, self.root)

    def test_escape(self):
        outside = Path(self.temp.name) / 'outside'
        outside.write_bytes(b'x')
        with self.assertRaises(BoundaryError):
            fingerprint_regular_file(outside, self.root)

    def test_hardlink(self):
        os.link(self.file, self.root / 'other')
        with self.assertRaises(BoundaryError):
            fingerprint_regular_file(self.file, self.root)

    def test_mapping_empty(self):
        self.assertFalse(mapping_evidence_gate(series_id=1, season=1, episode=1, providers=[])['approved'])

    def test_mapping_self_declared_not_enough(self):
        self.assertFalse(mapping_evidence_gate(series_id=1, season=1, episode=1, providers=[{'approved': True}])['approved'])

    def test_mapping_one_source(self):
        self.assertFalse(mapping_evidence_gate(series_id=1, season=1, episode=1, providers=[self.provider('a')])['approved'])

    def test_mapping_duplicate_authority(self):
        self.assertFalse(mapping_evidence_gate(series_id=1, season=1, episode=1, providers=[self.provider('a'), self.provider('a')])['approved'])

    def test_mapping_two_sources(self):
        self.assertTrue(mapping_evidence_gate(series_id=1, season=1, episode=1, providers=[self.provider('a'), self.provider('b')])['approved'])

    def test_mapping_wrong_episode(self):
        p = self.provider('a'); p['episode'] = 2
        self.assertFalse(mapping_evidence_gate(series_id=1, season=1, episode=1, providers=[p, self.provider('b')])['approved'])

    def test_mapping_out_of_range(self):
        self.assertFalse(mapping_evidence_gate(series_id=1, season=1, episode=7, providers=[self.provider('a'), self.provider('b')])['approved'])

    @staticmethod
    def provider(authority):
        return dict(authority=authority, authenticated=True, canonical=True, series_id=1, season=1, episode=1, record_digest='a'*64)

    def test_cancel_match(self):
        j, a, i = self.cancel_fixture()
        self.assertTrue(guarded_cancel_decision(job=j, attempt=a, inventory=i, current_generation=3))

    def test_cancel_generation_mismatch(self):
        j, a, i = self.cancel_fixture()
        self.assertFalse(guarded_cancel_decision(job=j, attempt=a, inventory=i, current_generation=4))

    def test_cancel_attempt_mismatch(self):
        j, a, i = self.cancel_fixture(); a['id'] = 8
        self.assertFalse(guarded_cancel_decision(job=j, attempt=a, inventory=i, current_generation=3))

    def test_cancel_hash_mismatch(self):
        j, a, i = self.cancel_fixture(); a['torrent_hash'] = 'b'*40
        self.assertFalse(guarded_cancel_decision(job=j, attempt=a, inventory=i, current_generation=3))

    def test_cancel_duplicate_inventory(self):
        j, a, i = self.cancel_fixture(); i.append(dict(i[0]))
        self.assertFalse(guarded_cancel_decision(job=j, attempt=a, inventory=i, current_generation=3))

    def test_cancel_delete_files(self):
        j, a, i = self.cancel_fixture(); j['delete_files'] = 1
        self.assertFalse(guarded_cancel_decision(job=j, attempt=a, inventory=i, current_generation=3))

    @staticmethod
    def cancel_fixture():
        h = 'a'*40
        return (dict(series_id=1, attempt_id=7, torrent_hash=h, generation=3, delete_files=0),
                dict(id=7, series_id=1, torrent_hash=h, generation=3, status='DOWNLOADING'),
                [dict(hash=h, generation=3)])

if __name__ == '__main__':
    unittest.main()

class Episode1SnapshotTests(unittest.TestCase):
    def setUp(self):
        import sqlite3
        from types import SimpleNamespace
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.media = self.root / 'e1.mkv'
        self.media.write_bytes(b'fixture')
        self.db = sqlite3.connect(':memory:')
        self.db.row_factory = sqlite3.Row
        self.addCleanup(self.db.close)
        self.db.executescript('''
            CREATE TABLE download_attempts(id INTEGER, series_id INTEGER, season INTEGER, episode INTEGER, status TEXT);
            CREATE TABLE staged_episodes(series_id INTEGER, season INTEGER, episode INTEGER, attempt_id INTEGER, status TEXT, staged_path TEXT, imported_path TEXT);
        ''')
        self.db.execute('INSERT INTO download_attempts VALUES(7,1,1,1,\'COMPLETED\')')
        self.db.execute('INSERT INTO staged_episodes VALUES(1,1,1,7,\'STAGED\',?,NULL)', (str(self.media),))
        self.controller = SimpleNamespace(TRIAL_STAGING_ROOT=self.root, TRIAL_LIBRARY_ROOT=self.root,
            staged_file_check=lambda *args: {'verified': True},
            imported_file_check=lambda *args: {'verified': True},
            check_file_stability=lambda *args: {'stable': True})

    def test_snapshot_success(self):
        from live_boundary_patch import verified_episode1_snapshot
        self.assertIsNotNone(verified_episode1_snapshot(self.controller,self.db,1,7))

    def test_snapshot_wrong_attempt(self):
        from live_boundary_patch import verified_episode1_snapshot
        self.assertIsNone(verified_episode1_snapshot(self.controller,self.db,1,8))

    def test_snapshot_probe_failure(self):
        from live_boundary_patch import verified_episode1_snapshot
        self.controller.staged_file_check=lambda *args: {'verified': False}
        self.assertIsNone(verified_episode1_snapshot(self.controller,self.db,1,7))

    def test_snapshot_stability_failure(self):
        from live_boundary_patch import verified_episode1_snapshot
        self.controller.check_file_stability=lambda *args: {'stable': False}
        self.assertIsNone(verified_episode1_snapshot(self.controller,self.db,1,7))

    def test_snapshot_replacement_during_probe(self):
        from live_boundary_patch import verified_episode1_snapshot
        def swap(*args):
            self.media.unlink()
            self.media.write_bytes(b'fixture')
            return {'verified': True}
        self.controller.staged_file_check=swap
        self.assertIsNone(verified_episode1_snapshot(self.controller,self.db,1,7))
