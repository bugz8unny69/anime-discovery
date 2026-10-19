import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from anime_trial_metadata import write_episode_nfo,write_series_nfo

class MetadataTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder=Path(self.temp.name)/"Show"
        self.folder.mkdir()
        self.video=self.folder/"Show - S01E02.mkv"
        self.video.write_bytes(b"placeholder")

    def test_local_metadata(self):
        series=write_series_nfo(self.folder,title="Example",tvdb_id="123",anidb_id="456")
        episode=write_episode_nfo(self.video,title="Example",season=1,episode=2,tvdb_id="123")
        self.assertEqual(ET.parse(series).getroot().findtext("title"),"Example")
        self.assertEqual(ET.parse(episode).getroot().findtext("episode"),"2")
        self.assertEqual(ET.parse(episode).getroot().find("uniqueid").text,"123")

    def test_invalid_episode_does_not_create_metadata(self):
        with self.assertRaises(ValueError):
            write_episode_nfo(self.video,title="Example",season=1,episode=0,tvdb_id="123")
        self.assertFalse(self.video.with_suffix(".nfo").exists())

if __name__=="__main__":
    unittest.main()
