"""Offline routing and recovery contracts for opted-in legacy magnet intake."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.nextgen.acquisition.metainfo_source import MetadataSourceConfigurationError
from src.nextgen.acquisition.legacy_magnet import make_bootstrap
from src.nextgen.acquisition.settings import DownloadOptions
from src.nextgen.acquisition.submission import Observation
from src.nextgen.job_contracts import Outcome
from src.nextgen.jobs.prepare_acquisition_job import registration
from src.nextgen.storage.job_queue import Claim
from src.nextgen.storage.sonarr_magnet_intake import MagnetIntent, MagnetPermit
from src.nextgen.sonarr_episode import VerifiedEpisode

HASH='a'*40
MAGNET='magnet:?xt=urn:btih:'+HASH
CLAIM=Claim(21,4,'PREPARE_ACQUISITION','{"evaluation_job_id":3}',1,'lease')


class LegacyWorkerRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_callback_used_only_when_normal_reader_waits(self):
        async def missing(source,configuration,cancelled):
            raise MetadataSourceConfigurationError()
        async def legacy(source,context):
            return Outcome('defer','TORRENT_METADATA_WAITING',delay_ms=60000)
        spec=registration(missing,legacy_bootstrap=legacy)
        context=SimpleNamespace(
            data=lambda:{'evaluation_job_id':3},claim=CLAIM,
            configuration=SimpleNamespace(value=lambda key:'/unused'),
            cancelled=asyncio.Event())
        with patch('src.nextgen.jobs.prepare_acquisition_job.load_acquisition_input',
                   return_value=SimpleNamespace(info_hash=HASH)):
            outcome=await spec.execute(context)
        self.assertEqual((outcome.kind,outcome.reason_code),
                         ('defer','TORRENT_METADATA_WAITING'))

    async def test_without_opt_in_preserves_existing_error(self):
        async def missing(source,configuration,cancelled):
            raise MetadataSourceConfigurationError()
        spec=registration(missing)
        context=SimpleNamespace(
            data=lambda:{'evaluation_job_id':3},claim=CLAIM,
            configuration=SimpleNamespace(value=lambda key:'/unused'),
            cancelled=asyncio.Event())
        with patch('src.nextgen.jobs.prepare_acquisition_job.load_acquisition_input',
                   return_value=SimpleNamespace(info_hash=HASH)):
            outcome=await spec.execute(context)
        self.assertEqual((outcome.kind,outcome.reason_code),
                         ('review','TORRENT_METADATA_CONFIGURATION_INVALID'))


class LegacyBootstrapTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.config=SimpleNamespace(value=lambda key:{
            'storage.database_path':'unused.sqlite',
            'qbittorrent.base_url':'http://localhost:8080',
            'storage.download_root':'/downloads',
            'qbittorrent.category':'anime',
            'qbittorrent.timeout_seconds':10,
        }[key])
        self.context=SimpleNamespace(
            claim=CLAIM,configuration=self.config,cancelled=asyncio.Event())
        self.source=SimpleNamespace(event_id=4,info_hash=HASH)
        self.secrets=SimpleNamespace(qbittorrent_credentials=lambda:Mock())
        self.identity=VerifiedEpisode(100,200,1,10)

    async def test_unrelated_event_never_contacts_qbittorrent(self):
        factory=Mock()
        cb=make_bootstrap(self.secrets,client_factory=factory)
        with patch('src.nextgen.acquisition.legacy_magnet.acquisition_identity',
                   return_value=None):
            self.assertIsNone(await cb(self.source,self.context))
        factory.assert_not_called()

    async def test_restart_recovers_admitted_torrent_without_sonarr_search(self):
        from src.nextgen.storage.sonarr_magnet_intake import _fingerprint
        root='/downloads/ad-'+'c'*32
        options=DownloadOptions('http://localhost:8080',root,'anime',10)
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN',
                            _fingerprint(4,HASH,'c'*32,options,4))
        probe=Mock(major=4,metadata_strategy='legacy_poll')
        owned=Mock()
        owned.inspect.return_value=Observation(
            HASH,'pausedDL',root,'anime',('ad-'+'c'*32,),False,())
        owned.poll_legacy_metadata.return_value=None
        journal=Mock()
        journal.existing.return_value=intent
        journal.reconcile.return_value='UNCERTAIN'
        factory=Mock(side_effect=[probe,owned])
        search_factory=Mock(side_effect=AssertionError('must not search'))
        cb=make_bootstrap(self.secrets,client_factory=factory,
                          journal_factory=lambda db:journal,
                          sonarr_factory=search_factory)
        with patch('src.nextgen.acquisition.legacy_magnet.acquisition_identity',
                   return_value=self.identity):
            result=await cb(self.source,self.context)
        self.assertEqual(result.kind,'defer')
        search_factory.assert_not_called()
        journal.authorize.assert_not_called()
        owned.add_legacy_magnet.assert_not_called()
        owned.poll_legacy_metadata.assert_called_once()

    async def test_upgrade_to_52_recovers_original_magnet_before_fetch(self):
        from src.nextgen.storage.sonarr_magnet_intake import _fingerprint
        root='/downloads/ad-'+'c'*32
        options=DownloadOptions('http://localhost:8080',root,'anime',10)
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN',
                            _fingerprint(4,HASH,'c'*32,options,4))
        probe=Mock(major=5,metadata_strategy='fetch')
        owned=Mock()
        owned.inspect.return_value=Observation(
            HASH,'pausedDL',root,'anime',('ad-'+'c'*32,),False,())
        owned.poll_legacy_metadata.return_value=None
        journal=Mock()
        journal.existing.return_value=intent
        journal.reconcile.return_value='UNCERTAIN'
        factory=Mock(side_effect=[probe,owned])
        search=Mock(side_effect=AssertionError('no second Sonarr search'))
        cb=make_bootstrap(self.secrets,client_factory=factory,
                          journal_factory=lambda db:journal,
                          sonarr_factory=search)
        with patch('src.nextgen.acquisition.legacy_magnet.acquisition_identity',
                   return_value=self.identity):
            result=await cb(self.source,self.context)
        self.assertEqual(result.kind,'defer')
        owned.poll_legacy_metadata.assert_called_once()
        journal.authorize.assert_not_called()
        owned.add_legacy_magnet.assert_not_called()
        search.assert_not_called()

    async def test_42_owned_metadata_defers_without_false_manifest(self):
        from src.nextgen.storage.sonarr_magnet_intake import _fingerprint
        root='/downloads/ad-'+'c'*32
        options=DownloadOptions('http://localhost:8080',root,'anime',10)
        intent=MagnetIntent(4,21,HASH,'c'*32,options,4,'UNCERTAIN',
                            _fingerprint(4,HASH,'c'*32,options,4))
        probe=Mock(major=4,metadata_strategy='legacy_poll')
        probe.inspect.return_value=None
        owned=Mock()
        observation=Observation(HASH,'pausedDL',root,'anime',
                                ('ad-'+'c'*32,),False,())
        owned.inspect.return_value=observation
        owned.poll_legacy_metadata.return_value=None
        journal=Mock()
        journal.existing.return_value=None
        journal.authorize.return_value=(intent,MagnetPermit(intent.fingerprint),())
        journal.reconcile.return_value='UNCERTAIN'
        release=SimpleNamespace(info_hash=HASH,magnet_url=MAGNET)
        search=SimpleNamespace(
            search=lambda identity:SimpleNamespace(candidates=(release,)),
            policy=SimpleNamespace(accepts=lambda row:True))
        factory=Mock(side_effect=[probe,owned])
        cb=make_bootstrap(self.secrets,client_factory=factory,
                          journal_factory=lambda db:journal,
                          sonarr_factory=lambda config,secrets:search)
        with patch('src.nextgen.acquisition.legacy_magnet.acquisition_identity',
                   return_value=self.identity):
            result=await cb(self.source,self.context)
        self.assertEqual((result.kind,result.reason_code),
                         ('defer','TORRENT_METADATA_WAITING'))
        journal.guard.assert_called_once()
        owned.add_legacy_magnet.assert_called_once_with(
            MAGNET,intent,journal.authorize.return_value[1])
        owned.poll_legacy_metadata.assert_called_once()
        journal.reconcile.assert_called_once()
