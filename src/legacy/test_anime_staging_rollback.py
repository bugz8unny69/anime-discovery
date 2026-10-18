import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_trial_staging import stage_verified

class StagingRollbackTests(unittest.TestCase):
    def test_metadata_failure_removes_staged_copy_not_source(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"episode.mkv"
            source.write_bytes(b"test media")
            trial=root/"trial"
            trial.mkdir()
            with patch("anime_trial_staging.write_episode_nfo",side_effect=OSError("disk full")):
                with self.assertRaises(OSError):
                    stage_verified(source,trial,title="Example",tvdb_id="123",
                                   season=1,episode=1,series_id=2)
            self.assertTrue(source.exists())
            self.assertEqual(list(trial.rglob("*.mkv")),[])

if __name__=="__main__":
    unittest.main()
