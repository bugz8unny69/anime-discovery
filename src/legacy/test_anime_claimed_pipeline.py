import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_claimed_pipeline import process_claimed

class FakeDB:
    in_transaction=False

class PipelineTests(unittest.TestCase):
    def test_incomplete_torrent_does_not_stage(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch("anime_claimed_pipeline.approved_dispatch",return_value={"series_id":4}), \
                 patch("anime_claimed_pipeline.acquire_claimed",return_value="a"*40), \
                 patch("anime_claimed_pipeline.completed_torrent_snapshot",return_value={"progress":0.5}), \
                 patch("anime_claimed_pipeline.stage_claimed") as stage:
                result=process_claimed(FakeDB(),1,infohash="a"*40,magnet_uri="magnet:?",
                    qb=object(),download_root=root,trial_root=root,title="Anime",tvdb_id=2)
                self.assertEqual(result["state"],"DEFERRED")
                stage.assert_not_called()

    def test_existing_staged_file_requires_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            torrent={"progress":1,"state":"uploading"}
            with patch("anime_claimed_pipeline.approved_dispatch",return_value={"series_id":4}), \
                 patch("anime_claimed_pipeline.acquire_claimed",return_value="a"*40), \
                 patch("anime_claimed_pipeline.completed_torrent_snapshot",return_value=torrent), \
                 patch("anime_claimed_pipeline.verified_media",return_value=root/"original.mkv"), \
                 patch("anime_claimed_pipeline.stage_claimed",side_effect=FileExistsError), \
                 patch("anime_claimed_pipeline.retain_recovery_record") as retain:
                result=process_claimed(FakeDB(),1,infohash="a"*40,magnet_uri="magnet:?",
                    qb=object(),download_root=root,trial_root=root,title="Anime",tvdb_id=2)
                self.assertEqual(result["state"],"NEEDS_REVIEW")
                retain.assert_not_called()

    def test_interrupted_stage_is_reconciled_without_overwrite(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"original.mkv"
            source.write_bytes(b"media")
            staged=root/"TVDB-2-S4"/"Season 01"/"S01E01.mkv"
            staged.parent.mkdir(parents=True)
            staged.write_bytes(b"media")
            torrent={"progress":1,"state":"uploading"}
            approval={"series_id":4,"season":1,"episode":1}
            with (patch("anime_claimed_pipeline.approved_dispatch",return_value=approval),
                  patch("anime_claimed_pipeline.acquire_claimed",return_value="a"*40),
                  patch("anime_claimed_pipeline.completed_torrent_snapshot",return_value=torrent),
                  patch("anime_claimed_pipeline.verified_media",return_value=source),
                  patch("anime_claimed_pipeline.stage_claimed",side_effect=FileExistsError),
                  patch("anime_claimed_pipeline.retain_recovery_record",return_value={"sha256":"abc"}) as retain):
                result=process_claimed(FakeDB(),1,infohash="a"*40,magnet_uri="magnet:?",
                    qb=object(),download_root=root,trial_root=root,title="Anime",tvdb_id=2)
                self.assertEqual(result["state"],"DONE")
                self.assertEqual(result["staged_path"],str(staged))
                retain.assert_called_once()
                self.assertEqual(staged.read_bytes(),b"media")

if __name__=="__main__":
    unittest.main()
