"""Whole-series Reject leaves no empty series/season folders behind."""
import hashlib
import json
import os
import tempfile
import unittest

from src.nextgen.storage.review_decisions import prune_series

SHOW = b'<?xml version="1.0"?><tvshow><title>Koori</title></tvshow>'
FOLDER = 'Koori no Jouheki _2026_ [tvdbid-459627] [anidbid-20168]'


class PruneSeriesTests(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp()
        os.makedirs(f'{self.root}/{FOLDER}/Season 02')
        with open(f'{self.root}/{FOLDER}/tvshow.nfo', 'wb') as f:
            f.write(SHOW)
        info = os.stat(self.root)
        self.manifest = json.dumps({
            'root': self.root, 'root_identity': [info.st_dev, info.st_ino],
            'entries': [{'role': 'series', 'path': FOLDER + '/tvshow.nfo',
                         'sha256': hashlib.sha256(SHOW).hexdigest()}]})

    def test_empty_series_is_removed(self):
        prune_series((self.manifest, self.manifest), lambda: None)
        self.assertEqual(os.listdir(self.root), [])

    def test_foreign_file_keeps_folders(self):
        open(f'{self.root}/{FOLDER}/Season 02/other.mkv', 'w').close()
        prune_series((self.manifest,), lambda: None)
        self.assertTrue(os.path.exists(f'{self.root}/{FOLDER}/tvshow.nfo'))
        self.assertTrue(os.path.exists(f'{self.root}/{FOLDER}/Season 02/other.mkv'))

    def test_changed_tvshow_nfo_is_kept(self):
        with open(f'{self.root}/{FOLDER}/tvshow.nfo', 'ab') as f:
            f.write(b'edited')
        prune_series((self.manifest,), lambda: None)
        self.assertEqual(os.listdir(f'{self.root}/{FOLDER}'), ['tvshow.nfo'])

    def test_missing_folder_is_fine(self):
        prune_series((self.manifest,), lambda: None)
        prune_series((self.manifest,), lambda: None)


if __name__ == '__main__':
    unittest.main()
