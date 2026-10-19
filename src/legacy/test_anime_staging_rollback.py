import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_trial_staging import stage_verified

class OptionalMetadataTests(unittest.TestCase):
    def test_nfo_failure_preserves_playable_staged_media(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"episode.mkv"
            source.write_bytes(b"test media")
            trial=root/"trial"
            trial.mkdir()
            with patch("anime_trial_staging.write_episode_nfo",side_effect=OSError("disk full")):
                dest=stage_verified(source,trial,title="Example",tvdb_id="123",
                                    season=1,episode=1,series_id=2)
            self.assertTrue(source.exists())
            self.assertEqual(dest.read_bytes(),source.read_bytes())
            self.assertTrue(dest.is_file())

if __name__=="__main__":
    unittest.main()
