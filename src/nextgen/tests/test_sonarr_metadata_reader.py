"""Offline Sonarr metadata fallback contracts; no network or workflow execution."""
import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from src.nextgen.acquisition.metainfo_source import (
    MetadataSourceConfigurationError, MetadataSourceWaiting, make_reader,
)
from src.nextgen.acquisition.sonarr_search import SearchResult
from src.nextgen.sonarr_episode import VerifiedEpisode

HASH='a'*40
MAGNET='magnet:?xt=urn:btih:'+HASH


class SonarrMetadataReaderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.source=SimpleNamespace(info_hash=HASH,event_id=25)
        self.configuration=SimpleNamespace(value=lambda key:{
            'storage.database_path':'unused.sqlite',
            'torrent_metadata.base_url':'',
            'torrent_metadata.timeout_seconds':30,
            'qbittorrent.base_url':'http://localhost:8080',
            'qbittorrent.timeout_seconds':30,
            'qbittorrent.category':'anime',
            'storage.download_root':'/var/downloads',
        }[key])
        self.secrets=SimpleNamespace(qbittorrent_credentials=lambda:SimpleNamespace())
        self.identity=VerifiedEpisode(100,200,1,10)
        self.sonarr=SimpleNamespace(
            search=lambda _:SearchResult(1,2,(SimpleNamespace(
                info_hash=HASH,magnet_url=MAGNET),)),
            policy=SimpleNamespace(accepts=lambda row:True))
        self.qb=Mock()
        self.qb.metadata_strategy='fetch'
        self.qb.fetch_metadata.return_value=(object(),b'metainfo')
        self.patches=[
            patch('src.nextgen.storage.sonarr_selection.acquisition_identity',
                  return_value=self.identity),
            patch('src.nextgen.acquisition.sonarr_search.Client.from_context',
                  return_value=self.sonarr),
            patch('src.nextgen.acquisition.qbittorrent.Client',return_value=self.qb),
        ]
        for item in self.patches:
            item.start()
            self.addCleanup(item.stop)

    async def test_verified_magnet_produces_same_metainfo_reader_output(self):
        reader=make_reader(sonarr_secrets=self.secrets)
        self.assertEqual(await reader(self.source,self.configuration,asyncio.Event()),
                         b'metainfo')
        self.qb.login.assert_called_once()
        self.qb.fetch_metadata.assert_called_once_with(MAGNET,HASH)

    async def test_pending_metadata_defers_without_submission(self):
        self.qb.fetch_metadata.return_value=None
        reader=make_reader(sonarr_secrets=self.secrets)
        with self.assertRaises(MetadataSourceWaiting):
            await reader(self.source,self.configuration,asyncio.Event())
        self.qb.add_stopped.assert_not_called()

    async def test_legacy_client_does_not_add_unverified_magnet(self):
        self.qb.metadata_strategy='guarded_export'
        reader=make_reader(sonarr_secrets=self.secrets)
        with self.assertRaises(MetadataSourceConfigurationError):
            await reader(self.source,self.configuration,asyncio.Event())
        self.qb.fetch_metadata.assert_not_called()
        self.qb.add_stopped.assert_not_called()

    async def test_unrelated_event_retains_original_configuration_requirement(self):
        from src.nextgen.storage import sonarr_selection
        with patch.object(sonarr_selection,'acquisition_identity',return_value=None):
            reader=make_reader(sonarr_secrets=self.secrets)
            with self.assertRaises(MetadataSourceConfigurationError):
                await reader(self.source,self.configuration,asyncio.Event())
        self.qb.login.assert_not_called()
