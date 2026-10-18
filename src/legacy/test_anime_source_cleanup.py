import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_source_retention import retain_recovery_record
from anime_source_cleanup import cleanup_source

class FakeQB:
    def __init__(self):
        self.present=True
        self.removed=[]
    def contains_hash(self,key):
        return self.present
    def remove_torrent(self,key,delete_files=False):
        self.removed.append((key,delete_files))
        self.present=False

class CleanupTests(unittest.TestCase):
    @patch("anime_source_retention.confirmed_jp_en",return_value=True)
    def test_verified_cleanup_requires_explicit_approval(self,_):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            source=root/"source.mkv"
            staged=root/"staged.mkv"
            source.write_bytes(b"matching video")
            staged.write_bytes(source.read_bytes())
            db=sqlite3.connect(":memory:",isolation_level=None)
            try:
                retain_recovery_record(db,infohash="a"*40,magnet_uri="magnet:?xt=urn:btih:"+"a"*40,
                                       source=source,staged=staged,notification_id=3)
                qb=FakeQB()
                with self.assertRaises(PermissionError):
                    cleanup_source(db,3,source,qb)
                self.assertTrue(source.exists())
                result=cleanup_source(db,3,source,qb,approved=True)
                self.assertTrue(result["source_removed"])
                self.assertFalse(source.exists())
                self.assertTrue(staged.exists())
                self.assertEqual(qb.removed,[("a"*40,False)])
            finally:
                db.close()

    @patch("anime_source_retention.confirmed_jp_en",return_value=True)
    def test_hash_mismatch_blocks_record(self,_):
        with tempfile.TemporaryDirectory() as tmp:
            source=Path(tmp)/"a.mkv"
            staged=Path(tmp)/"b.mkv"
            source.write_bytes(b"123")
            staged.write_bytes(b"456")
            with sqlite3.connect(":memory:",isolation_level=None) as db:
                with self.assertRaises(ValueError):
                    retain_recovery_record(db,infohash="a"*40,magnet_uri="magnet:?",
                                           source=source,staged=staged,notification_id=4)

if __name__=="__main__":
    unittest.main()
