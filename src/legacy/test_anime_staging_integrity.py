import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_trial_staging import stage_verified

class StagingIntegrityTests(unittest.TestCase):
    def test_corrupt_temporary_copy_never_published(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            source=root/"original.mkv"
            source.write_bytes(b"source bytes")
            trial=root/"trial"
            trial.mkdir()
            real_open=open
            def corrupt_staged(path,*args,**kwargs):
                if str(path).endswith(".tmp") and args and args[0]=="rb":
                    from io import BytesIO
                    return BytesIO(b"wrong bytes!")
                return real_open(path,*args,**kwargs)
            with patch("builtins.open",side_effect=corrupt_staged):
                with self.assertRaisesRegex(ValueError,"checksum"):
                    stage_verified(source,trial,title="Example",tvdb_id=123,
                                   season=1,episode=1,series_id=2)
            self.assertEqual(source.read_bytes(),b"source bytes")
            self.assertEqual(list(trial.rglob("*.mkv")),[])

if __name__=="__main__":
    unittest.main()
