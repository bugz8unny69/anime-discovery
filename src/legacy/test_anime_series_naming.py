"""Verified English series naming and staged media path regressions."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_series_naming import clean_series_name,resolve_series_name
from anime_trial_staging import stage_verified,staged_destination


class SeriesNamingTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.execute("""CREATE TABLE series (
            id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,title TEXT)""")
        self.db.execute("""INSERT INTO series VALUES
            (1,'tvdb','389597','[MiniDual] Solo Leveling S01E02 1080p')""")

    def test_tvdb_translation_wins_over_release_title(self):
        name=resolve_series_name(self.db,1,"389597",
            english_title="Solo Leveling")
        self.assertEqual(name,"Solo Leveling")
        self.assertNotIn("S01E02",name)

    def test_approved_unique_alias_is_valid_offline_fallback(self):
        name=resolve_series_name(self.db,1,"389597",
            series_map={"Solo Leveling":{"tvdb_id":389597,"anidb_id":123}})
        self.assertEqual(name,"Solo Leveling")

    def test_no_verified_clean_name_blocks_staging(self):
        with self.assertRaisesRegex(ValueError,"English series name unavailable"):
            resolve_series_name(self.db,1,"389597")

    def test_different_tvdb_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"mismatch"):
            resolve_series_name(self.db,1,"111",english_title="Solo Leveling")

    def test_invalid_chars_are_sanitized_and_release_labels_refused(self):
        self.assertEqual(clean_series_name("Solo: Leveling / Part 2"),"Solo Leveling Part 2")
        for name in ("[Group] Solo Leveling","Solo Leveling S01E02","  ..  ",
                     "TVDB-389597-S1","Solo Leveling 1080p"):
            with self.subTest(name=name),self.assertRaises(ValueError):
                clean_series_name(name)

    def test_stage_path_and_nfo_use_canonical_name_and_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); trial=root/"Anime-Trial";trial.mkdir()
            original=root/"episode.mkv";original.write_bytes(b"not empty")
            dest=stage_verified(original,trial,title="Solo Leveling",tvdb_id=389597,
                season=1,episode=2,series_id=1,english_title="Solo Leveling")
            self.assertEqual(dest,trial/"Solo Leveling"/"Season 01"/"S01E02.mkv")
            self.assertIn("389597", (trial/"Solo Leveling"/"tvshow.nfo").read_text())
            self.assertEqual(staged_destination(trial,title="Solo Leveling",season=1,
                episode=2,suffix=".mkv"),dest)
            with self.assertRaises(FileExistsError):
                stage_verified(original,trial,title="Solo Leveling",tvdb_id=389597,
                    season=1,episode=2,series_id=1)

    def test_wrong_existing_nfo_identity_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); trial=root/"trial"; trial.mkdir()
            original=root/"episode.mkv";original.write_bytes(b"video")
            wrong=trial/"Solo Leveling";wrong.mkdir()
            (wrong/"tvshow.nfo").write_text(
                "<tvshow><uniqueid type='tvdb'>999999</uniqueid></tvshow>")
            with self.assertRaisesRegex(ValueError,"belongs to another"):
                stage_verified(original,trial,title="Solo Leveling",tvdb_id=389597,
                    season=1,episode=2,series_id=1)
            self.assertFalse((wrong/"Season 01"/"S01E02.mkv").exists())

if __name__=="__main__":
    unittest.main()
