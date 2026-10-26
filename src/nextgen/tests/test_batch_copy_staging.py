"""Filesystem regression: batch staging is a pinned COPY, never a torrent move."""
import hashlib
import os
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest

from src.nextgen.acquisition.media import signature
from src.nextgen.staging import Publisher, specification, root_identity


class ArtifactJournalDouble:
    def __init__(self):
        self.records={}
        self.by_id={}
        self.sequence=0
        self.moves=0

    def guard(self,claim):pass

    def artifact(self,claim,root,name):
        record=self.records.get((root,name))
        return None if record is None else dict(record)

    def register(self,claim,root,name):
        info=os.stat(os.path.join(root,name),follow_symlinks=False)
        directory=os.stat(root)
        self.sequence+=1
        record={'id':self.sequence,
                'root':[directory.st_dev,directory.st_ino],
                'file':[info.st_dev,info.st_ino],
                'phase':'TEMP'}
        self.records[(root,name)]=record
        self.by_id[self.sequence]=record
        return dict(record)

    def register_move(self,*args):
        self.moves+=1
        raise AssertionError('batch staging must never rename qB source data')

    def intent(self,claim,artifact):
        self.by_id[artifact]['phase']='PUBLISH_UNCERTAIN'

    def confirm(self,claim,artifact):
        self.by_id[artifact]['phase']='PUBLISHED'


class BatchCopyPublisherTests(unittest.TestCase):
    def test_copy_only_staging_preserves_original_torrent_video(self):
        with tempfile.TemporaryDirectory() as base:
            origin=Path(base)/'downloads'
            trial=Path(base)/'trial'
            origin.mkdir()
            trial.mkdir()
            video=origin/'Show S01E01.mkv'
            payload=b'header '+(b'episode file data'*1200)
            video.write_bytes(payload)
            initial=signature(video.stat())
            root_identity_value=[origin.stat().st_dev,origin.stat().st_ino]
            evidence={
                'path':video.name,
                'root':root_identity_value,
                'file':list(initial),
                'sha256':hashlib.sha256(payload).hexdigest(),
                'duration_ms':120000,
                'languages':['eng','jpn'],
            }
            intent=SimpleNamespace(
                options=SimpleNamespace(download_root=str(origin)))
            plan=specification(intent,evidence,
                (123,1001,456,1,1,2001,'Show'),str(trial),1)
            plan['root_identity']=root_identity(str(trial))
            plan['transfer']='COPY'
            journal=ArtifactJournalDouble()
            publisher=Publisher(journal,SimpleNamespace(job_id=42),
                                threading.Event(),allow_root=True)
            receipts=publisher.publish(plan)
            self.assertEqual(len(receipts),3)
            self.assertEqual(journal.moves,0)
            self.assertEqual(video.read_bytes(),payload)
            self.assertEqual(signature(video.stat()),initial)
            destination=trial/plan['entries'][0]['path']
            self.assertEqual(destination.read_bytes(),payload)
            self.assertNotEqual((video.stat().st_dev,video.stat().st_ino),
                                (destination.stat().st_dev,destination.stat().st_ino))
            # Re-enter after simulated completion replay: no overwrite.
            again=publisher.publish(plan)
            self.assertEqual(again,receipts)
            self.assertEqual(video.read_bytes(),payload)


if __name__=='__main__':
    unittest.main()
