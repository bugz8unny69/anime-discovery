"""Mock qB file manifests and disposable paths only."""
import os
import tempfile
import unittest
from pathlib import Path
from anime_cleanup_file_safety import preflight

H="a"*40
OTHER="b"*40

class FakeQB:
    def __init__(self,save):
        self.save=str(save)
        self.files=[{"name":"release/episode.mkv","size":8}]
        self.others=[]
        self.state="pausedDL"
    def torrent_details(self,h):
        return {"hash":H,"save_path":self.save,"state":self.state}
    def torrent_files(self,h):
        return self.files if h==H else [{"name":"release/episode.mkv"}]
    def torrent_inventory(self):
        return [{"hash":H,"save_path":self.save}]+self.others

class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.download=Path(self.tmp.name)/"downloads"
        self.trial=Path(self.tmp.name)/"trial"
        self.download.mkdir()
        self.trial.mkdir()
        (self.download/"release").mkdir()
        self.media=self.download/"release"/"episode.mkv"
        self.media.write_bytes(b"download")
        self.qb=FakeQB(self.download)

    def check(self,**kwargs):
        return preflight(self.qb,H,download_root=self.download,
                         trial_root=self.trial,**kwargs)

    def test_stopped_owned_download_inventory(self):
        plan=self.check()
        self.assertEqual(plan["files"],[str(self.media)])
        self.assertEqual(plan["bytes"],8)
        self.assertTrue(self.media.exists())

    def test_active_torrent_is_not_eligible(self):
        self.qb.state="downloading"
        with self.assertRaisesRegex(ValueError,"Stop the torrent"):
            self.check()

    def test_shared_file_from_different_torrent_is_protected(self):
        self.qb.others=[{"hash":OTHER,"save_path":str(self.download)}]
        with self.assertRaisesRegex(ValueError,"shared"):
            self.check()
        self.assertTrue(self.media.exists())

    def test_symlink_and_hardlink_are_preserved(self):
        self.media.unlink()
        outside=Path(self.tmp.name)/"outside.mkv"
        outside.write_bytes(b"do not touch")
        self.media.symlink_to(outside)
        with self.assertRaisesRegex(ValueError,"Unverified download file"):
            self.check()
        self.media.unlink()
        os.link(outside,self.media)
        with self.assertRaisesRegex(ValueError,"hardlinked"):
            self.check()
        self.assertTrue(outside.exists())

    def test_path_escape_and_wrong_download_root_are_rejected(self):
        for name in ("../outside.mkv","/etc/passwd","release/../../outside.mkv"):
            self.qb.files=[{"name":name}]
            with self.assertRaises(ValueError):
                self.check()
        self.qb.files=[{"name":"release/episode.mkv"}]
        self.qb.save=str(self.trial)
        with self.assertRaisesRegex(ValueError,"outside download root"):
            self.check()

    def test_sonarr_storage_overlap_is_rejected(self):
        with self.assertRaisesRegex(ValueError,"Sonarr-managed"):
            self.check(sonarr_root=self.download)

if __name__=="__main__":
    unittest.main()
