import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from anime_trial_metadata import write_episode_nfo,write_series_nfo,tvdb_english_title

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

    def test_english_display_title_and_xml_escape(self):
        series=write_series_nfo(self.folder,title="俺だけレベルアップな件",
            tvdb_id=389597,anidb_id=1234,english_title="Solo & Leveling <English>")
        episode=write_episode_nfo(self.video,title="俺だけレベルアップな件",
            tvdb_id=389597,season=1,episode=2,english_title="Solo & Leveling <English>")
        self.assertEqual(ET.parse(series).getroot().findtext("title"),"Solo & Leveling <English>")
        self.assertEqual(ET.parse(episode).getroot().findtext("showtitle"),"Solo & Leveling <English>")
        self.assertEqual(ET.parse(series).getroot().find("uniqueid").text,"389597")
        self.assertIn(b"&amp;",series.read_bytes())

    def test_no_english_title_falls_back_without_guessing(self):
        series=write_series_nfo(self.folder,title="俺だけレベルアップな件",
            tvdb_id=389597)
        self.assertEqual(ET.parse(series).getroot().findtext("title"),"俺だけレベルアップな件")

    def test_tvdb_english_translation_only(self):
        received=[]
        def fetch(url,bearer=None):
            received.append((url,bearer))
            return {"data":{"name":"Solo Leveling","language":"eng"}}
        self.assertEqual(tvdb_english_title(389597,"secret",login=lambda key:"token",fetch=fetch),"Solo Leveling")
        self.assertTrue(received[0][0].endswith("/series/389597/translations/eng"))
        self.assertEqual(received[0][1],"token")
        self.assertIsNone(tvdb_english_title(389597,"secret",login=lambda key:"token",
            fetch=lambda *args,**kwargs:{"data":{"name":""}}))
        self.assertIsNone(tvdb_english_title(389597,"secret",login=lambda key:"token",
            fetch=lambda *args,**kwargs:(_ for _ in ()).throw(TimeoutError())))

    def test_invalid_episode_does_not_create_metadata(self):
        with self.assertRaises(ValueError):
            write_episode_nfo(self.video,title="Example",season=1,episode=0,tvdb_id="123")
        self.assertFalse(self.video.with_suffix(".nfo").exists())

if __name__=="__main__":
    unittest.main()
