"""Disposable filesystem tests for metadata-only recovery after a verified stage."""
import hashlib
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from anime_trial_staging import staged_destination,reconcile_staged_metadata

class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.dest=staged_destination(self.root,title="Example Anime",
            season=2,episode=3,suffix=".mkv")
        self.dest.parent.mkdir(parents=True)
        self.original=b"identical verified bytes"
        self.dest.write_bytes(self.original)
        self.args=dict(title="Example Anime",tvdb_id=76543,
                       season=2,episode=3)

    def reconcile(self):
        reconcile_staged_metadata(self.dest,**self.args)

    def test_missing_nfos_repaired_without_copying_video(self):
        original=self.dest.stat()
        source_digest=hashlib.sha256(self.original).hexdigest()
        self.reconcile()
        show=self.dest.parent.parent/"tvshow.nfo"
        episode=self.dest.with_suffix(".nfo")
        self.assertTrue(show.is_file())
        self.assertTrue(episode.is_file())
        self.assertEqual(ET.parse(episode).getroot().findtext("season"),"2")
        self.assertEqual(ET.parse(episode).getroot().findtext("episode"),"3")
        self.assertEqual(hashlib.sha256(self.dest.read_bytes()).hexdigest(),
                         source_digest)
        self.assertEqual(self.dest.stat().st_ino,original.st_ino)
        self.reconcile()  # idempotent after checkpoint interruption
        self.assertEqual(self.dest.read_bytes(),self.original)

    def test_conflicting_existing_nfo_blocks_reconciliation(self):
        (self.dest.parent.parent/"tvshow.nfo").write_text(
            '<tvshow><uniqueid type="tvdb">999</uniqueid></tvshow>')
        with self.assertRaisesRegex(ValueError,"identity mismatch"):
            self.reconcile()
        self.assertEqual(self.dest.read_bytes(),self.original)
        self.assertFalse(self.dest.with_suffix(".nfo").exists())

    def test_symlinked_episode_metadata_never_overwritten(self):
        outside=self.root/"external.nfo"
        outside.write_text("do not overwrite")
        self.dest.with_suffix(".nfo").symlink_to(outside)
        with self.assertRaisesRegex(ValueError,"Unsafe existing NFO"):
            self.reconcile()
        self.assertEqual(outside.read_text(),"do not overwrite")
        self.assertEqual(self.dest.read_bytes(),self.original)

if __name__=="__main__":
    unittest.main()
