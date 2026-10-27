"""Isolated pre-manifest magnet journal contracts; no daemon or CI required."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import patch
import sqlite3
import unittest

from src.nextgen.acquisition.contracts import AcquisitionInput
from src.nextgen.acquisition.metadata import TorrentFile, ObservedInventory, AcquisitionConflict, MetadataInvalid
from src.nextgen.acquisition.settings import DownloadOptions
from src.nextgen.acquisition.submission import Observation, ClientInvalid
from src.nextgen.storage.job_queue import Claim
from src.nextgen.storage.sonarr_magnet_intake import (
    MagnetJournal, MagnetPermit, _fingerprint,
)

HASH='a'*40
MARKER='c'*32


class MagnetJournalTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE acquisition_plans(reservation_id INTEGER);
            CREATE TABLE sonarr_magnet_intents (
                event_id INTEGER PRIMARY KEY,job_id INTEGER,plan_id INTEGER,
                tvdb_episode INTEGER,info_hash TEXT UNIQUE,marker TEXT,
                api_major INTEGER,base_url TEXT,save_path TEXT,
                category TEXT,timeout_seconds INTEGER,inventory_json TEXT,state TEXT,
                created_at_ms INTEGER,updated_at_ms INTEGER
            );
        """)
        self.options=DownloadOptions('http://localhost:8080','/downloads','anime',10)
        self.source=AcquisitionInput(1,2,3,4,HASH,'0'*64,1,1,10,'Example')
        self.claim=Claim(21,4,'PREPARE_ACQUISITION','{}',1,'lease')
        self.journal=MagnetJournal('/unused')
        @contextmanager
        def connection():
            yield self.db
        self.journal.queue=SimpleNamespace(
            connection=connection,now=lambda:123,
            _owns=lambda db,claim,now:None)
        patcher1=patch('src.nextgen.storage.sonarr_magnet_intake._source',
                       return_value=self.source)
        patcher2=patch('src.nextgen.storage.sonarr_magnet_intake._verified_candidate',
                       return_value=(12,10))
        patcher3=patch('src.nextgen.storage.sonarr_magnet_intake.append_job_history',
                       return_value=None)
        for p in (patcher1,patcher2,patcher3):
            p.start()
            self.addCleanup(p.stop)

    def test_authorization_is_committed_once_before_network(self):
        intent,permit,_=self.journal.authorize(
            self.claim,self.source,self.options,4,False)
        self.assertIsInstance(permit,MagnetPermit)
        self.assertEqual(intent.options.download_root,'/downloads/ad-'+intent.marker)
        self.assertEqual(self.db.execute(
            "SELECT state FROM sonarr_magnet_intents").fetchone(),('UNCERTAIN',))
        permit.take(intent)
        with self.assertRaises(ClientInvalid):
            permit.take(intent)
        same,second,_=self.journal.authorize(
            self.claim,self.source,self.options,4,False)
        self.assertEqual(same,intent)
        self.assertIsNone(second)

    def test_absence_after_restart_never_rearms_permit(self):
        intent,permit,_=self.journal.authorize(
            self.claim,self.source,self.options,4,False)
        self.assertIsNotNone(permit)
        recovered,permit,_=self.journal.authorize(
            self.claim,self.source,self.options,4,True)
        self.assertIsNone(permit)
        self.assertEqual(recovered.marker,intent.marker)

    def test_external_same_hash_is_never_automatically_adopted(self):
        intent,permit,_=self.journal.authorize(
            self.claim,self.source,self.options,4,True)
        self.assertEqual(intent.state,'EXTERNAL')
        self.assertIsNone(permit)
        self.assertEqual(self.journal.reconcile(self.claim,intent,None),'EXTERNAL')

    def test_ownership_reconciliation_is_exact_and_stopped(self):
        intent,_,_=self.journal.authorize(
            self.claim,self.source,self.options,4,False)
        files=(TorrentFile(0,'Example S01E10.mkv',123),)
        owned=Observation(HASH,'pausedDL',intent.options.download_root,
                          'anime',('ad-'+intent.marker,),False,files)
        self.assertEqual(self.journal.reconcile(self.claim,intent,owned),
                         'OWNED_STOPPED')
        self.assertEqual(self.db.execute(
            "SELECT state FROM sonarr_magnet_intents").fetchone(),
            ('OWNED_STOPPED',))

    def test_immutable_observed_inventory_is_not_a_fabricated_metainfo_hash(self):
        intent,_,_=self.journal.authorize(
            self.claim,self.source,self.options,4,False)
        files=(TorrentFile(0,'Example S01E10.mkv',123),)
        owned=Observation(HASH,'pausedDL',intent.options.download_root,
                          'anime',('ad-'+intent.marker,),False,files)
        self.assertEqual(self.journal.reconcile(self.claim,intent,owned),
                         'OWNED_STOPPED')
        inventory=ObservedInventory.from_observation(owned)
        self.journal.capture(self.claim,intent,self.source,inventory)
        self.journal.capture(self.claim,intent,self.source,inventory)
        import json
        data=json.loads(self.db.execute(
            'SELECT inventory_json FROM sonarr_magnet_intents').fetchone()[0])
        self.assertEqual(data['evidence'],'qbittorrent_stopped_inventory')
        self.assertNotIn('info_sha256',data)
        changed=ObservedInventory(HASH,
            (TorrentFile(0,'Example S01E10.mkv',124),),0)
        with self.assertRaises(AcquisitionConflict):
            self.journal.capture(self.claim,intent,self.source,changed)

    def test_qb_inventory_cannot_disguise_multiple_videos_as_single_episode(self):
        with self.assertRaises(MetadataInvalid):
            ObservedInventory(HASH,(
                TorrentFile(0,'Example S01E10.mkv',100),
                TorrentFile(1,'Other S01E11.mkv',100),
            ),0)

    def test_qb_inventory_rejects_unsafe_extra_file_type(self):
        with self.assertRaises(MetadataInvalid):
            ObservedInventory(HASH,(
                TorrentFile(0,'Example S01E10.mkv',100),
                TorrentFile(1,'run.sh',2),
            ),0)

    def test_mismatched_owned_marker_needs_review(self):
        intent,_,_=self.journal.authorize(
            self.claim,self.source,self.options,4,False)
        foreign=Observation(HASH,'pausedDL',intent.options.download_root,
                            'anime',('ad-'+'d'*32,),False,())
        self.assertEqual(self.journal.reconcile(self.claim,intent,foreign),
                         'REVIEW')
