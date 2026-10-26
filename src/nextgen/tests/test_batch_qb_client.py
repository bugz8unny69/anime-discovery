"""Offline tests of batch-only stopped-add qB adapter and one-shot token."""
import unittest

from src.nextgen.acquisition.metadata import parse_batch_metainfo
from src.nextgen.acquisition.settings import DownloadOptions
from src.nextgen.acquisition.submission import ClientInvalid
from src.nextgen.batch.qb_client import BatchClient
from src.nextgen.storage.batch_acquisition_candidate import BatchAcquisitionCandidate
from src.nextgen.storage.batch_submission_journal import (
    BatchSubmissionIntent, BatchSendPermit,
)
from src.nextgen.tests.test_acquisition_metadata import metadata


class BatchQbClientTests(unittest.TestCase):
    def setUp(self):
        files=[
            {b'length':100,b'path':[b'Season 01',b'Shiki S01E01.mkv']},
            {b'length':100,b'path':[b'Season 01',b'Shiki S01E02.mkv']},
            {b'length':100,b'path':[b'OVA',b'Shiki OVA 01.mkv']},
        ]
        self.raw,digest=metadata(name=b'Shiki',files=files)
        inventory=parse_batch_metainfo(self.raw,digest)
        self.options=DownloadOptions('http://localhost:8080',
                                     '/tmp/anime/ad-'+'a'*32,'trial',10)
        candidate=BatchAcquisitionCandidate(21,22,digest,inventory.info_sha256,
                                            0,((1,0),(2,1)),(2,),200)
        self.intent=BatchSubmissionIntent(candidate,inventory,self.options,
                                          'a'*32,'UNCERTAIN','b'*64,5)
        self.calls=[]
        self.client=BatchClient.__new__(BatchClient)
        self.client._sid='private-session'
        self.client.major=5
        self.client.options=self.options
        self.client._request=lambda path,**kwargs:self.calls.append((path,kwargs))

    def test_immutable_metadata_and_stopped_only_fields(self):
        permit=BatchSendPermit(self.intent.fingerprint)
        self.client.add_batch_stopped(self.raw,self.intent,permit)
        self.assertEqual(len(self.calls),1)
        path,kwargs=self.calls[0]
        self.assertEqual(path,'torrents/add')
        self.assertIn(b'name="stopped"',kwargs['body'])
        self.assertIn(b'name="autoTMM"',kwargs['body'])
        self.assertIn(b'ad-'+'a'.encode()*32,kwargs['body'])
        self.assertNotIn(b'name="filePrio"',kwargs['body'])
        with self.assertRaises(ClientInvalid):
            self.client.add_batch_stopped(self.raw,self.intent,permit)
        self.assertEqual(len(self.calls),1)

    def test_changed_or_unexpected_metadata_does_not_consume_permit(self):
        permit=BatchSendPermit(self.intent.fingerprint)
        with self.assertRaises(ClientInvalid):
            self.client.add_batch_stopped(self.raw+b'junk',self.intent,permit)
        self.assertEqual(self.calls,[])
        self.client.add_batch_stopped(self.raw,self.intent,permit)
        self.assertEqual(len(self.calls),1)


if __name__=='__main__':
    unittest.main()
