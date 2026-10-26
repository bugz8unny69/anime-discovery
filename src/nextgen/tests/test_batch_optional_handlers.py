"""Construction tests: opt-in batch stages remain outside default composition."""
import unittest

from src.nextgen.dashboard.presentation import HANDLERS
from src.nextgen.job_contracts import Registry
from src.nextgen.jobs.submit_batch_job import registration as submit_batch
from src.nextgen.jobs.transfer_batch_job import registration as transfer_batch
from src.nextgen.jobs.verify_batch_probe_job import registration as verify_probe
from src.nextgen.jobs.unlock_batch_job import registration as unlock_batch
from src.nextgen.providers.configuration import build_worker


async def dummy_metainfo(*args):
    raise AssertionError('Construction may not fetch torrent metadata')


class BatchOptionalHandlersTests(unittest.TestCase):
    def test_opt_in_batch_chain_has_all_required_successors(self):
        registry=Registry((
            submit_batch(dummy_metainfo,object(),transfer_kind='TRANSFER_BATCH'),
            transfer_batch(dummy_metainfo,object(),
                           verification_kind='VERIFY_BATCH_PROBE'),
            verify_probe(dummy_metainfo,unlock_kind='UNLOCK_BATCH'),
            unlock_batch(dummy_metainfo,object()),
        ))
        self.assertIsNotNone(registry)
        for code in ('SUBMIT_BATCH','TRANSFER_BATCH','VERIFY_BATCH_PROBE',
                     'UNLOCK_BATCH'):
            HANDLERS.require(code)

    def test_untrusted_sync_metadata_reader_is_rejected(self):
        for build in (
                lambda:submit_batch(lambda *_:None,object()),
                lambda:transfer_batch(lambda *_:None,object()),
                lambda:verify_probe(lambda *_:None),
                lambda:unlock_batch(lambda *_:None,object())):
            with self.subTest(build=build),self.assertRaises(ValueError):
                build()


if __name__=='__main__':
    unittest.main()
