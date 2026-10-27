"""Offline version-gated magnet metadata transport contracts (no network or CI)."""
import unittest
from unittest.mock import Mock, patch

from src.nextgen.acquisition.qbittorrent import Client, _Protocol
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
        self.assertEqual(self.client((2,8,15),4).metadata_strategy,'guarded_export')
        self.assertEqual(self.client((2,10,0),5).metadata_strategy,'guarded_export')
        self.assertEqual(self.client((2,5,1),4).metadata_strategy,'legacy_poll')
        with self.assertRaises(ClientUnsupported):
            self.client((2,2,9),4).metadata_strategy

    def test_protocol_names_cover_submission_start_stop(self):
        old=_Protocol(4,(2,8,15))
        new=_Protocol(5,(2,11,9))
        self.assertEqual((old.stopped_parameter,old.start_endpoint,old.stop_endpoint),
                         ('paused','torrents/resume','torrents/pause'))
        self.assertEqual((new.stopped_parameter,new.start_endpoint,new.stop_endpoint),
                         ('stopped','torrents/start','torrents/stop'))

    def test_42_protocol_omits_unsupported_add_fields(self):
        old=_Protocol(4,(2,5,1))
        self.assertFalse(old.inline_tags)
        self.assertFalse(old.indexed_files)
        self.assertEqual(old.file_index({'name':'first.mkv'},0),0)
        self.assertEqual(old.add_fields(True),
                         {'paused':'true','autoTMM':'false'})
        self.assertEqual(old.start_endpoint,'torrents/resume')
        self.assertEqual(old.stop_endpoint,'torrents/pause')

    def test_42_submission_tags_after_one_permitted_add(self):
        import json
        client=self.client((2,5,1),4)
        client.options.download_root='/media/downloads/ad-'+'c'*32
        intent=Mock(options=client.options,api_major=4,fingerprint='f'*64)
        intent.plan.manifest.info_hash=HASH
        intent.plan.marker='c'*32
        observed={'hash':HASH,'save_path':client.options.download_root,
                  'category':'anime','auto_tmm':False,'state':'pausedDL'}
        client._request.side_effect=[
            (b'Ok.',{}),(json.dumps([observed]).encode(),{}),(b'',{}),
        ]
        permit=SendPermit('f'*64)
        client.add_stopped(MAGNET,intent,permit)
        self.assertEqual(client._request.call_count,3)
        add,check,tag=client._request.call_args_list
        self.assertEqual(add.args,('torrents/add',))
        self.assertNotIn('tags',add.kwargs['form'])
        self.assertNotIn('contentLayout',add.kwargs['form'])
        self.assertNotIn('useDownloadPath',add.kwargs['form'])
        self.assertEqual(check.args,('torrents/info',))
        self.assertEqual(tag.args,('torrents/addTags',))
        self.assertEqual(tag.kwargs['form'],
                         {'hashes':HASH,'tags':'ad-'+'c'*32})
        with self.assertRaises(ClientInvalid):
            client.add_stopped(MAGNET,intent,permit)
        self.assertEqual(client._request.call_count,3)

    def test_42_does_not_tag_preexisting_other_destination(self):
        import json
        client=self.client((2,5,1),4)
        client.options.download_root='/media/downloads/ad-'+'c'*32
        intent=Mock(options=client.options,api_major=4,fingerprint='f'*64)
        intent.plan.manifest.info_hash=HASH
        intent.plan.marker='c'*32
        client._request.side_effect=[
            (b'Ok.',{}),
            (json.dumps([{'hash':HASH,'save_path':'/someone/else',
                          'category':'anime','auto_tmm':False,
                          'state':'pausedDL'}]).encode(),{}),
        ]
        with self.assertRaises(ClientInvalid):
            client.add_stopped(MAGNET,intent,SendPermit('f'*64))
        self.assertEqual([r.args[0] for r in client._request.call_args_list],
                         ['torrents/add','torrents/info'])

    def test_legacy_metainfo_export_requires_webapi_2814(self):
        from src.nextgen.acquisition.submission import ClientUnsupported
        legacy=self.client((2,5,1),4)
        with self.assertRaises(ClientUnsupported):
            legacy.export_metainfo(HASH)
        legacy._request.assert_not_called()

    def test_legacy_probe_requires_proven_ownership_and_two_stable_reads(self):
        import json
        client=self.client((2,5,1),4)
        root='/media/downloads/ad-'+'c'*32
        client.options.download_root=root
        row={'hash':HASH,'auto_tmm':False,'tags':'ad-'+'c'*32,
             'save_path':root,'category':'anime','state':'pausedDL'}
        files=[{'name':'episode.mkv','size':1024}]
        client._request.side_effect=[
            (json.dumps([row]).encode(),{}),(json.dumps(files).encode(),{}),
            (json.dumps([row]).encode(),{}),(json.dumps(files).encode(),{}),
        ]
        result=client.inspect_legacy_metadata(HASH,'c'*32,root)
        self.assertEqual(len(result.files),1)
        self.assertEqual(client._request.call_count,4)
        client._request.reset_mock()
        with self.assertRaises(ClientInvalid):
            client.inspect_legacy_metadata(HASH,'d'*32,root)

    def test_legacy_probe_rejects_changed_inventory(self):
        import json
        client=self.client((2,5,1),4)
        root='/media/downloads/ad-'+'c'*32
        client.options.download_root=root
        row={'hash':HASH,'auto_tmm':False,'tags':'ad-'+'c'*32,
             'save_path':root,'category':'anime','state':'pausedDL'}
        client._request.side_effect=[
            (json.dumps([row]).encode(),{}),
            (json.dumps([{'name':'episode.mkv','size':1024}]).encode(),{}),
            (json.dumps([row]).encode(),{}),
            (json.dumps([{'name':'different.mkv','size':1024}]).encode(),{}),
        ]
        with self.assertRaises(ClientInvalid):
            client.inspect_legacy_metadata(HASH,'c'*32,root)

    def test_42_file_lists_without_index_use_stable_response_order(self):
        import json
        client=self.client((2,5,1),4)
        client._request.side_effect=[
            (json.dumps([{'hash':HASH,'auto_tmm':False,'tags':'ad-'+'c'*32,
                          'save_path':'/media/downloads','category':'anime',
                          'state':'pausedDL'}]).encode(),{}),
            (json.dumps([{'name':'anime.mkv','size':100},
                         {'name':'anime.srt','size':10}]).encode(),{}),
        ]
        observed=client.inspect(HASH)
        self.assertEqual([file.index for file in observed.files],[0,1])
        self.assertEqual([file.path for file in observed.files],
                         ['anime.mkv','anime.srt'])

    def test_42_pre_manifest_add_is_single_use_and_tagged_by_readback(self):
        import json
        from src.nextgen.acquisition.settings import DownloadOptions
        from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent,MagnetPermit
        client=self.client((2,5,1),4)
        options=DownloadOptions('http://localhost:8080',
                                '/downloads/ad-'+'c'*32,'anime',10)
        client.options=options
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN','f'*64)
        row={'hash':HASH,'save_path':options.download_root,
             'category':'anime','auto_tmm':False,'tags':'','state':'pausedDL'}
        client._request.side_effect=[
            (b'Ok.',{}),(json.dumps([row]).encode(),{}),(b'',{})]
        permit=MagnetPermit('f'*64)
        client.add_legacy_magnet(MAGNET,intent,permit)
        self.assertEqual(
            [call.args[0] for call in client._request.call_args_list],
            ['torrents/add','torrents/info','torrents/addTags'])
        self.assertEqual(client._request.call_args_list[0].kwargs['form']['paused'],
                         'true')
        with self.assertRaises(ClientInvalid):
            client.add_legacy_magnet(MAGNET,intent,permit)
        self.assertEqual(client._request.call_count,3)

    def test_42_delayed_hash_readback_does_not_repeat_submission(self):
        import json
        from src.nextgen.acquisition.settings import DownloadOptions
        from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent,MagnetPermit
        client=self.client((2,5,1),4)
        options=DownloadOptions('http://localhost:8080',
                                '/downloads/ad-'+'c'*32,'anime',10)
        client.options=options
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN','f'*64)
        row={'hash':HASH,'save_path':options.download_root,
             'category':'anime','auto_tmm':False,'tags':'','state':'pausedDL'}
        client._request.side_effect=[
            (b'Ok.',{}),(b'[]',{}),(json.dumps([row]).encode(),{}),(b'',{})]
        with patch('time.sleep') as sleep:
            client.add_legacy_magnet(MAGNET,intent,MagnetPermit('f'*64))
        self.assertEqual(
            [c.args[0] for c in client._request.call_args_list],
            ['torrents/add','torrents/info','torrents/info','torrents/addTags'])
        sleep.assert_called_once()

    def test_42_foreign_path_cannot_be_tagged_after_magnet_add(self):
        import json
        from src.nextgen.acquisition.settings import DownloadOptions
        from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent,MagnetPermit
        client=self.client((2,5,1),4)
        options=DownloadOptions('http://localhost:8080',
                                '/downloads/ad-'+'c'*32,'anime',10)
        client.options=options
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN','f'*64)
        row={'hash':HASH,'save_path':'/downloads/other',
             'category':'anime','auto_tmm':False,'tags':'','state':'metaDL'}
        client._request.side_effect=[
            (b'Ok.',{}),(json.dumps([row]).encode(),{})]
        with self.assertRaises(ClientInvalid):
            client.add_legacy_magnet(MAGNET,intent,MagnetPermit('f'*64))
        self.assertEqual(
            [call.args[0] for call in client._request.call_args_list],
            ['torrents/add','torrents/info'])

    def test_42_metadata_poll_stops_after_bounded_resume(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from src.nextgen.acquisition.metadata import TorrentFile
        from src.nextgen.acquisition.submission import Observation
        from src.nextgen.acquisition.settings import DownloadOptions
        from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent
        client=self.client((2,5,1),4)
        options=DownloadOptions('http://localhost:8080',
                                '/downloads/ad-'+'c'*32,'anime',10)
        client.options=options
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN','f'*64)
        def observed(state,files=()):
            return Observation(HASH,state,options.download_root,'anime',
                               ('ad-'+'c'*32,),False,files)
        after_files=(TorrentFile(0,'Example.mkv',100),)
        with patch.object(client,'inspect',side_effect=[
                observed('pausedDL'),observed('metaDL'),
                observed('metaDL',after_files)]) as reads:
            with patch.object(client,'stop_legacy_metadata',
                              return_value='stopped') as stop:
                result=client.poll_legacy_metadata(
                    intent,SimpleNamespace(is_set=lambda:False),
                    attempts=3,interval=0,sleep=lambda _:None)
        self.assertEqual(result,'stopped')
        self.assertEqual(reads.call_count,3)
        self.assertEqual(client._request.call_args.args,('torrents/resume',))
        stop.assert_called_once_with(intent)

    def test_42_default_metadata_window_waits_beyond_two_seconds(self):
        from types import SimpleNamespace
        from src.nextgen.acquisition.metadata import TorrentFile
        from src.nextgen.acquisition.submission import Observation
        from src.nextgen.acquisition.settings import DownloadOptions
        from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent
        client=self.client((2,5,1),4)
        options=DownloadOptions('http://localhost:8080',
                                '/downloads/ad-'+'c'*32,'anime',10)
        client.options=options
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN','f'*64)
        def observation(state,files=()):
            return Observation(HASH,state,options.download_root,'anime',
                               ('ad-'+'c'*32,),False,files)
        # Early metadata polls are empty; the same original torrent eventually
        # provides its file list. Simulate elapsed time without sleeping.
        snapshots=[observation('pausedDL')]+[observation('metaDL')]*9+[
            observation('metaDL',(TorrentFile(0,'Episode.mkv',100),))]
        with patch.object(client,'inspect',side_effect=snapshots) as inspected:
            with patch.object(client,'stop_legacy_metadata',
                              return_value='stopped') as stopped:
                result=client.poll_legacy_metadata(
                    intent,SimpleNamespace(is_set=lambda:False),
                    sleep=lambda _:None)
        self.assertEqual(result,'stopped')
        self.assertEqual(inspected.call_count,11)
        stopped.assert_called_once_with(intent)
        self.assertEqual([call.args[0] for call in client._request.call_args_list],
                         ['torrents/resume'])

    def test_42_metadata_poll_refuses_foreign_marker(self):
        from types import SimpleNamespace
        from src.nextgen.acquisition.submission import Observation
        from src.nextgen.acquisition.settings import DownloadOptions
        from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent
        client=self.client((2,5,1),4)
        options=DownloadOptions('http://localhost:8080',
                                '/downloads/ad-'+'c'*32,'anime',10)
        client.options=options
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN','f'*64)
        with patch.object(client,'inspect',return_value=Observation(
                HASH,'pausedDL',options.download_root,'anime',
                ('ad-'+'d'*32,),False,())):
            with self.assertRaises(ClientInvalid):
                client.poll_legacy_metadata(
                    intent,SimpleNamespace(is_set=lambda:False))
        client._request.assert_not_called()

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

    def test_transport_accepts_202_only_for_metadata_polling(self):
        class Response:
            headers={}
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def getcode(self):return 202
            def read(self,size):return b'{"infohash_v1":"'+HASH.encode()+b'"}'
        client=self.client((2,11,9))
        client.options.base_url='http://localhost:8080'
        client.options.timeout_seconds=5
        del client._request  # Exercise the real HTTP adapter, not the helper mock.
        client._transport=lambda request,timeout:Response()
        self.assertIsNone(client.fetch_metadata(HASH,HASH))

    def test_save_metadata_conflict_remains_pending(self):
        import io
        import urllib.error
        class Response:
            headers={}
            def __init__(self,code,raw):
                self.code,self.raw=code,raw
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def getcode(self):return self.code
            def read(self,size):return self.raw
        client=self.client((2,11,9))
        client.options.base_url='http://localhost:8080'
        client.options.timeout_seconds=5
        requests=[]
        def transport(request,timeout):
            requests.append(request.full_url)
            if request.full_url.endswith('saveMetadata'):
                raise urllib.error.HTTPError(request.full_url,409,'pending',{},io.BytesIO())
            return Response(200,b'{"infohash_v1":"'+HASH.encode()+b'","info":{}}')
        del client._request  # Exercise the real HTTP adapter, including HTTP 409.
        client._transport=transport
        self.assertIsNone(client.fetch_metadata(HASH,HASH))
        self.assertEqual(len(requests),2)

    def test_hash_only_response_is_pending_not_ready(self):
        client=self.client((2,11,9))
        client._request.return_value=(b'{"infohash_v1":"'+HASH.encode()+b'"}',{})
        self.assertIsNone(client.fetch_metadata(HASH,HASH))
        client._request.assert_called_once_with(
            'torrents/fetchMetadata',form={'source':HASH},limit=4194304)

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
        client.add_stopped(MAGNET,intent,permit)
        self.assertEqual(client._request.call_args.args,('torrents/add',))
        self.assertEqual(client._request.call_args.kwargs['form']['stopped'],'true')
        self.assertEqual(client._request.call_args.kwargs['form']['urls'],MAGNET)
        with self.assertRaises(ClientInvalid):
            client.add_stopped(MAGNET,intent,permit)
        client._request.assert_called_once()

    def test_same_submission_interface_uses_legacy_paused_parameter(self):
        client=self.client((2,8,15),major=4)
        intent=Mock(options=client.options,api_major=4,fingerprint='f'*64)
        intent.plan.manifest.info_hash=HASH
        intent.plan.marker='c'*32
        client.add_stopped(MAGNET,intent,SendPermit('f'*64))
        args,kwargs=client._request.call_args
        self.assertEqual(args,('torrents/add',))
        self.assertEqual(kwargs['form']['paused'],'true')
        self.assertEqual(kwargs['form']['urls'],MAGNET)
        self.assertNotIn('stopCondition',kwargs['form'])
