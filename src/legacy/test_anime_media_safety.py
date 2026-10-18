import tempfile
import unittest
from pathlib import Path
from anime_media_completion import verified_media

class MediaSafetyTests(unittest.TestCase):
    def test_symlinked_intermediate_directory_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            actual=root/"real"
            actual.mkdir()
            (actual/"video.mkv").write_bytes(b"data")
            (root/"link").symlink_to(actual,target_is_directory=True)
            torrent={"progress":1,"state":"uploading",
                     "files":[{"name":"link/video.mkv","progress":1}]}
            with self.assertRaisesRegex(ValueError,"Symlinked"):
                verified_media(torrent,root)

    def test_checking_torrent_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/"video.mkv").write_bytes(b"data")
            torrent={"progress":1,"state":"checkingUP",
                     "files":[{"name":"video.mkv","progress":1}]}
            with self.assertRaisesRegex(ValueError,"not fully downloaded"):
                verified_media(torrent,root)

if __name__=="__main__":
    unittest.main()
