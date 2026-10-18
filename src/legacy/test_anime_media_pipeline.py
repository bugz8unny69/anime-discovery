import tempfile
import unittest
from pathlib import Path
from anime_media_completion import verified_media
from anime_trial_staging import stage_verified

class MediaTests(unittest.TestCase):
    def test_completion_and_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            downloads=root/"downloads"
            trial=root/"Anime-Trial"
            downloads.mkdir()
            trial.mkdir()
            video=downloads/"episode.mkv"
            video.write_bytes(b"example media payload")
            snapshot={"progress":1,"state":"uploading",
                      "files":[{"name":"episode.mkv","progress":1}]}
            source=verified_media(snapshot,downloads)
            dest=stage_verified(source,trial,title="Example",tvdb_id=123,
                                season=1,episode=2,series_id=5)
            self.assertEqual(dest.read_bytes(),video.read_bytes())
            self.assertTrue(dest.with_suffix(".nfo").is_file())
            self.assertTrue((dest.parent.parent/"tvshow.nfo").is_file())
            with self.assertRaises(FileExistsError):
                stage_verified(source,trial,title="Example",tvdb_id=123,
                               season=1,episode=2,series_id=5)

    def test_incomplete_media_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                verified_media({"progress":0.9,"state":"downloading","files":[]},tmp)

if __name__=="__main__":
    unittest.main()
