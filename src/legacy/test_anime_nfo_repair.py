import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_nfo_repair import repair_nfo

class RepairTests(unittest.TestCase):
    def test_metadata_repair_does_not_modify_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            series=Path(tmp)/"TVDB-123-S2"
            season=series/"Season 01"
            season.mkdir(parents=True)
            media=season/"S01E01.mkv"
            media.write_bytes(b"untouched")
            with patch("anime_nfo_repair.write_series_nfo") as a,patch("anime_nfo_repair.write_episode_nfo") as b:
                result=repair_nfo(media,title="Example",tvdb_id=123,season=1,episode=1)
            self.assertTrue(result["media_preserved"])
            self.assertEqual(media.read_bytes(),b"untouched")
            a.assert_called_once()
            b.assert_called_once()

if __name__=="__main__":
    unittest.main()
