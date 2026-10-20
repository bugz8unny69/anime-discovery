"""Offline completed-file probe and qB stop/reselect/start gate tests."""
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_batch_completion import (
    inspect_completed_episode, unlock_verified_remaining, BatchNeedsReview)
from anime_qb_e01_probe import start_e01_probe
from anime_qb_manifest_intake import submit_poll_pause
from anime_trial_policy import record_verified_window, window_for
from anime_trial_size_policy import MB
from test_anime_qb_e01_probe import SelectionQB, HASH, MAGNET


class ProofQB(SelectionQB):
    def __init__(self, root):
        super().__init__(ready_after=0)
        self.root = Path(root)
        self.progresses = {}
        self.manifest_sizes = [100] * 12
        self.records[HASH] = {"hash": HASH, "category": "other",
                              "tags": "", "state": "downloading"}
        # A new owned torrent is created through normal submit_poll_pause.
        self.records.clear()

    def torrent_identity(self, infohash):
        item = super().torrent_identity(infohash)
        return {**item, "save_path": str(self.root)} if item else None

    def torrent_files(self, infohash):
        files = super().torrent_files(infohash)
        for file in files:
            i = file["index"]
            file["size"] = self.manifest_sizes[i]
            file["progress"] = self.progresses.get(i, 0)
        return files

    def stop_owned_torrent(self, infohash):
        self.stops += 1
        self.records[infohash]["state"] = "pausedDL"
        return "pausedDL"


class CompletionTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.db = sqlite3.connect(":memory:", isolation_level=None)
        self.addCleanup(self.db.close)
        self.qb = ProofQB(self.root)
        self.qb.manifest_sizes[0] = 101
        self.stop = submit_poll_pause(
            self.db, HASH, MAGNET, self.qb, attempts=3, interval=0,
            sleep=lambda _: None)
        record_verified_window(self.db,tvdb_id=123,anidb_id=456,season=2,
            unit_key="season",mode="SEASON",start_episode=1,
            evidence_ref="anime-lists:123:456:season2")
        self.window = window_for(self.db,tvdb_id=123,anidb_id=456,season=2)
        self.mapping = {n:n for n in range(1,13)}
        start_e01_probe(self.db,HASH,self.qb,season=2,stopped_manifest=self.stop,
            verified_window=self.window,verified_episode_map=self.mapping)
        folder = self.root / "Season 02"
        folder.mkdir()
        (folder / "Anime S02E01.mkv").write_bytes(b"x"*101)

    def verify(self, runner=lambda _: True):
        return inspect_completed_episode(self.db,HASH,self.qb,
            window=self.window,stopped_manifest=self.stop,
            episode_map=self.mapping,episode=1,download_root=self.root,
            runner=runner)

    def unlock(self):
        return unlock_verified_remaining(self.db,HASH,self.qb,
            window=self.window,stopped_manifest=self.stop,
            episode_map=self.mapping,sleep=lambda _:None)

    def test_no_unlock_before_completed_ffprobe(self):
        self.assertEqual(self.verify()["state"],"DEFERRED")
        with self.assertRaisesRegex(BatchNeedsReview,"No durable"):
            self.unlock()
        self.assertEqual(self.qb.priorities[1],0)
        self.assertEqual(self.qb.start_calls,1)

    def test_first_audio_rejected_keeps_next_five_skipped(self):
        self.qb.progresses[0]=1
        with self.assertRaisesRegex(BatchNeedsReview,"JAPANESE_ENGLISH_REQUIRED"):
            self.verify(lambda _:False)
        with self.assertRaises(BatchNeedsReview):
            self.unlock()
        self.assertEqual(self.qb.start_calls,1)
        self.assertEqual(self.qb.priorities[1],0)

    def test_verified_then_selects_exact_six_and_skips_seven_plus(self):
        self.qb.progresses[0]=1
        with self.assertLogs("anime_discovery.trial",level="INFO") as logs:
            proof=self.verify()
            started=self.unlock()
        self.assertEqual(proof["state"],"VERIFIED")
        self.assertEqual(proof["file_index"],0)
        self.assertEqual(started["state"],"UNLOCKED")
        self.assertEqual([self.qb.priorities[i] for i in range(12)],
                         [1]*6+[0]*6)
        self.assertEqual(self.qb.start_calls,2)
        self.assertIn("event=BATCH_EPISODES_UNLOCKED","\n".join(logs.output))
        # Restart with the same DB and torrent does not reprioritize.
        repeat=self.unlock()
        self.assertTrue(repeat["already_running"])
        self.assertEqual(self.qb.start_calls,2)

    def test_source_size_mismatch_refuses_audio_proof(self):
        self.qb.progresses[0]=1
        (self.root/"Season 02/Anime S02E01.mkv").write_bytes(b"x"*99)
        with self.assertRaisesRegex(BatchNeedsReview,"size/path mismatch"):
            self.verify()
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM sqlite_master WHERE name='anime_batch_audio_proofs'").fetchone()[0],0)

    def test_symlink_component_refused(self):
        self.qb.progresses[0]=1
        folder=self.root/"Season 02"
        (folder/"Anime S02E01.mkv").unlink()
        (folder/"Anime S02E01.mkv").symlink_to(self.root/"other.mkv")
        with self.assertRaises(BatchNeedsReview):
            self.verify()

    def test_wrong_window_refuses_no_unlock(self):
        self.qb.progresses[0]=1
        with self.assertRaises(PermissionError):
            inspect_completed_episode(self.db,HASH,self.qb,
                window={**self.window,"start":13},
                stopped_manifest=self.stop,episode_map=self.mapping,
                episode=1,download_root=self.root,runner=lambda _:True)
        self.assertEqual(self.qb.priorities[1],0)


if __name__=="__main__":
    unittest.main()
