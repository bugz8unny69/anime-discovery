"""Offline version-gated magnet metadata transport contracts (no network or CI)."""
import unittest
from unittest.mock import Mock

from src.nextgen.acquisition.qbittorrent import Client, _Protocol
from src.nextgen.acquisition.settings import DownloadOptions, DownloadCredentials
from src.nextgen.acquisition.submission import ClientInvalid, ClientUnsupported, SendPermit

HASH='a'*40
MAGNET='magnet:?xt=urn:btih:'+HASH


class MagnetMetadataTests(unittest.TestCase):
    def client(self,api_version,major=5):
        # Exercise the public transport methods without making HTTP requests.
        client=object.__new__(Client)
        client._sid='session'
        client.major=major
        client.api_version=api_version
        client.protocol=_Protocol(major,api_version)
        client.options=Mock(download_root='/media/downloads',category='anime')
        client._request=Mock()
        return client

    def test_version_selection_uses_web_api_not_app_major(self):
        self.assertEqual(self.client((2,11,9)).metadata_strategy,'fetch')
        self.assertEqual(self.client((2,8,15),4).metadata_strategy,'stopped_magnet')
        self.assertEqual(self.client((2,10,0),5).metadata_strategy,'stopped_magnet')
        with self.assertRaises(ClientUnsupported):
            self.client((2,8,14),4).metadata_strategy

    def test_protocol_names_cover_submission_start_stop(self):
        old=_Protocol(4,(2,8,15))
        new=_Protocol(5,(2,11,9))
        self.assertEqual((old.stopped_parameter,old.start_endpoint,old.stop_endpoint),
                         ('paused','torrents/resume','torrents/pause'))
        self.assertEqual((new.stopped_parameter,new.start_endpoint,new.stop_endpoint),
                         ('stopped','torrents/start','torrents/stop'))

    def test_metadata_fetch_is_hash_bound_and_pending_is_not_failure(self):
        client=self.client((2,11,9))
        client._request.return_value=(b'{}',{})
        self.assertIsNone(client.fetch_metadata(MAGNET,HASH))
        client._request.assert_called_once_with(
            'torrents/fetchMetadata',form={'source':MAGNET},limit=4194304)
        client._request.reset_mock()
        with self.assertRaises(ClientInvalid):
            client.fetch_metadata('magnet:?xt=urn:btih:'+'b'*40,HASH)
        client._request.assert_not_called()

    def test_metadata_hash_mismatch_does_not_export_or_authorize(self):
        client=self.client((2,11,9))
        client._request.return_value=(b'{"infohash_v1":"'+b'b'*40+b'"}',{})
        with self.assertRaises(ClientInvalid):
            client.fetch_metadata(MAGNET,HASH)
        client._request.assert_called_once()

    def test_magnet_submission_consumes_original_single_use_permit(self):
        client=self.client((2,11,9))
        client._request.return_value=(b'Ok.',{})
        intent=Mock(options=client.options,api_major=5,fingerprint='f'*64)
        intent.plan.manifest.info_hash=HASH
        intent.plan.marker='c'*32
        permit=SendPermit('f'*64)
        client.add_magnet_stopped(MAGNET,intent,permit)
        self.assertEqual(client._request.call_args.args,('torrents/add',))
        self.assertEqual(client._request.call_args.kwargs['form']['stopped'],'true')
        self.assertEqual(client._request.call_args.kwargs['form']['urls'],MAGNET)
        with self.assertRaises(ClientInvalid):
            client.add_magnet_stopped(MAGNET,intent,permit)
        client._request.assert_called_once()

    def test_legacy_add_uses_metadata_stop_condition(self):
        client=self.client((2,8,15),major=4)
        client._request.return_value=(b'Ok.',{})
        client.add_magnet_metadata(MAGNET,HASH,'c'*32)
        args,kwargs=client._request.call_args
        self.assertEqual(args,('torrents/add',))
        self.assertEqual(kwargs['form']['stopCondition'],'MetadataReceived')
        self.assertEqual(kwargs['form']['paused'],'false')
        self.assertEqual(kwargs['form']['tags'],'ad-'+'c'*32)
        self.assertEqual(kwargs['form']['urls'],MAGNET)
        with self.assertRaises(ClientInvalid):
            client.add_magnet_metadata(MAGNET,'b'*40,'c'*32)
