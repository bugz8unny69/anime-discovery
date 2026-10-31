"""Cancellation cleanup deletes what the work owns; real local files, fake qBittorrent."""
from pathlib import Path
import tempfile
import unittest

from src.nextgen.acquisition.submission import ClientUnavailable, ClientAuthenticationFailed, Observation
from src.nextgen.cancellation_service import CancellationService
from src.nextgen import cancel_cleanup
from src.nextgen.tests import test_torrent_transfer as fixture
from src.nextgen.tests.test_torrent_submission import Secrets


class CancellationCleanupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=fixture.TorrentTransferTests.asyncSetUp
    rows=fixture.TorrentTransferTests.rows
    source=fixture.TorrentTransferTests.source
    worker=fixture.TorrentTransferTests.worker
    queued=fixture.TorrentTransferTests.queued

    async def setup_download(self):
        worker=self.worker()
        self.store.update({'storage':{'download_root':str(self.root/'downloads')}},expected_revision=2)
        await self.queued(worker);await worker.attempt()
        self.job=self.rows("SELECT job_id FROM jobs WHERE kind='DOWNLOAD_TORRENT'")[0][0]
        self.payload_root=Path(self.snapshot.observation.save_path)
        self.payload_root.mkdir(parents=True)
        self.video=self.payload_root/self.snapshot.observation.files[0].path
        self.video.write_bytes(b'v'*100)
        (self.payload_root/'leftover.part').write_bytes(b'x')  # Anything in ad-* goes too.
        self.deleted=[]
        return worker

    def service(self,mode='normal'):
        test=self
        class FakeClient:
            def __init__(self,*args):pass
            def login(self):
                if mode=='auth':raise ClientAuthenticationFailed()
            def delete_owned(self,info_hash,marker):
                if mode=='down':raise ClientUnavailable()
                test.deleted.append((info_hash,marker));return True
        return CancellationService(self.store.read(),Secrets(),client_factory=FakeClient)

    async def test_cancel_deletes_torrent_and_whole_download_folder_and_frees_slot(self):
        await self.setup_download()
        self.assertEqual(self.service().cancel(self.job)['cleanup_state'],'COMPLETE')
        self.assertEqual(len(self.deleted),1)
        self.assertFalse(self.payload_root.exists())
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='DOWNLOAD_TORRENT'"),[('CANCELED',)])
        self.assertEqual(self.rows('SELECT state FROM episode_reservations'),[('RELEASED',)])

    async def test_qbittorrent_down_waits_then_finishes(self):
        await self.setup_download()
        self.assertEqual(self.service('down').cancel(self.job)['cleanup_state'],'PENDING')
        self.assertTrue(self.video.exists())
        self.assertEqual(self.service().cleanup(self.job)['cleanup_state'],'COMPLETE')
        self.assertFalse(self.payload_root.exists())

    async def test_missing_folder_counts_as_done(self):
        await self.setup_download()
        import shutil;shutil.rmtree(self.payload_root)
        self.assertEqual(self.service().cancel(self.job)['cleanup_state'],'COMPLETE')

    async def test_wrong_password_stops_for_review_naming_the_cause(self):
        await self.setup_download()
        result=self.service('auth').cancel(self.job)
        self.assertEqual(result['cleanup_state'],'REVIEW')
        self.assertIn('login',result['failed_check'])
        self.assertTrue(self.video.exists())


class OwnershipGuardTests(unittest.TestCase):
    def test_only_a_folder_named_for_its_marker_is_deleted(self):
        marker='a'*32
        with tempfile.TemporaryDirectory() as root:
            other=Path(root)/'downloads';other.mkdir();(other/'keep.mkv').write_bytes(b'x')
            cancel_cleanup.remove_download_folder(str(other),marker)
            self.assertTrue((other/'keep.mkv').exists())
            mine=Path(root)/('ad-'+marker);mine.mkdir();(mine/'v.mkv').write_bytes(b'x')
            cancel_cleanup.remove_download_folder(str(mine),marker)
            self.assertFalse(mine.exists())
            cancel_cleanup.remove_download_folder(str(mine),marker)  # Already gone: fine.

    def test_torrent_without_our_tag_is_left_alone(self):
        from src.nextgen.acquisition.qbittorrent import Client
        client=Client.__new__(Client);client.protocol=object();sent=[]
        client._request=lambda path,**kw:sent.append(path) or (b'',{})
        h='b'*40;marker='c'*32
        def seen(tags):return Observation(h,'stoppedDL','/d/ad-'+marker,'anime',tags,False,())
        client.inspect=lambda *a,**k:seen(('sonarr',))
        self.assertFalse(client.delete_owned(h,marker));self.assertEqual(sent,[])
        client.inspect=lambda *a,**k:None
        self.assertFalse(client.delete_owned(h,marker));self.assertEqual(sent,[])
        client.inspect=lambda *a,**k:seen(('ad-'+marker,))
        self.assertTrue(client.delete_owned(h,marker));self.assertEqual(sent,['torrents/delete'])

    def test_staging_outside_its_root_or_in_keep_is_never_touched(self):
        with tempfile.TemporaryDirectory() as tmp:
            staging=Path(tmp)/'staging';keep=Path(tmp)/'keep'
            season=staging/'Show'/'Season 01';season.mkdir(parents=True);keep.mkdir()
            video=season/'Show - S01E01.mkv';video.write_bytes(b'v')
            (staging/'Show'/'tvshow.nfo').write_bytes(b'n')
            outside=Path(tmp)/'other.mkv';outside.write_bytes(b'o')
            kept=keep/'k.mkv';kept.write_bytes(b'k')
            cancel_cleanup.remove_staging(
                [(str(video),str(staging)),(str(outside),str(staging)),(str(kept),str(staging))],
                [(str(staging/'Show'),str(staging))],keep_root=str(keep))
            self.assertFalse((staging/'Show').exists())  # Only tvshow.nfo was left.
            self.assertTrue(outside.exists());self.assertTrue(kept.exists())
