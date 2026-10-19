import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_media_flow import stage_claimed

class SourceFirstTests(unittest.TestCase):
    def test_bad_source_audio_never_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"episode.mkv"
            source.write_bytes(b"video")
            trial=root/"trial"
            trial.mkdir()
            db=sqlite3.connect(":memory:",isolation_level=None)
            try:
                db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY,info_hash TEXT)")
                db.execute("CREATE TABLE verified_series_identity(notification_id INTEGER PRIMARY KEY,tvdb_id TEXT)")
                db.execute("INSERT INTO notifications VALUES(1,?)",("a"*40,))
                db.execute("INSERT INTO verified_series_identity VALUES(1,'123')")
                torrent={"hash":"a"*40}
                approval={"series_id":2,"season":1,"episode":1}
                with patch("anime_media_flow.approved_dispatch",return_value=approval), \
                     patch("anime_media_flow.verified_media",return_value=source), \
                     patch("anime_media_flow.confirmed_jp_en",return_value=False), \
                     patch("anime_media_flow.stage_verified") as stage:
                    with self.assertRaisesRegex(ValueError,"Japanese and English"):
                        stage_claimed(db,1,torrent,root,trial,title="Example",tvdb_id="123")
                    stage.assert_not_called()
                self.assertEqual(list(trial.rglob("*.mkv")),[])
            finally:
                db.close()

    def test_good_source_audio_allows_staging(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"episode.mkv"
            source.write_bytes(b"video")
            db=sqlite3.connect(":memory:",isolation_level=None)
            try:
                db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY,info_hash TEXT)")
                db.execute("CREATE TABLE verified_series_identity(notification_id INTEGER PRIMARY KEY,tvdb_id TEXT)")
                db.execute("INSERT INTO notifications VALUES(1,?)",("b"*40,))
                db.execute("INSERT INTO verified_series_identity VALUES(1,'123')")
                with patch("anime_media_flow.approved_dispatch",return_value={"series_id":2,"season":1,"episode":1}), \
                     patch("anime_media_flow.verified_media",return_value=source), \
                     patch("anime_media_flow.confirmed_jp_en",return_value=True), \
                     patch("anime_media_flow.stage_verified",return_value=root/"staged.mkv") as stage:
                    result=stage_claimed(db,1,{"hash":"b"*40},root,root,title="Example",tvdb_id="123")
                    self.assertEqual(result,root/"staged.mkv")
                    stage.assert_called_once()
            finally:
                db.close()

if __name__=="__main__":
    unittest.main()
