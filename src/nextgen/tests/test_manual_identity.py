"""Manual match regression tests (local-only; no CI execution)."""
import tempfile
import unittest
from pathlib import Path

from src.nextgen.storage.sqlite import connect, initialize
from src.nextgen.storage.manual_identity import ManualMatchError, _key, for_release


class ManualMatchTests(unittest.TestCase):
    def test_alias_is_episode_independent(self):
        first = _key("Example Anime S01E01 1080p WEB-DL")
        second = _key("Example Anime S01E03 1080p WEB-DL")
        self.assertEqual(first, second)

    def test_season_scoped_match(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "db.sqlite"
            db = connect(path)
            initialize(db)
            db.execute(
                "INSERT INTO manual_identity_matches "
                "(alias_key,tvdb_season,anidb_id,tvdb_series_id,title) VALUES(?,?,?,?,?)",
                (_key("Example Anime S01E01 1080p WEB-DL"),1,123,456,"Example Anime"))
            db.commit()
            db.close()
            match = for_release(str(path),"Example Anime S01E03 1080p WEB-DL",1)
            self.assertEqual(match["anime"]["anidb_id"],123)
            self.assertEqual(match["anime"]["tvdb_series_id"],456)
            self.assertEqual(match["episodes"],[])
            self.assertIsNone(for_release(str(path),"Example Anime S02E03 1080p WEB-DL",2))


if __name__ == "__main__":
    unittest.main()
