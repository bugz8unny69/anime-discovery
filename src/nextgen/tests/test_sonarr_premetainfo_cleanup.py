"""Offline pre-manifest cancellation: only empty, exactly owned magnets can retire."""
from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch
import sqlite3
import unittest

from src.nextgen.acquisition.submission import Observation
from src.nextgen.cancellation import CancellationError
from src.nextgen.cancellation_service import CancellationService


HASH='a'*40
MARKER='c'*32
ROOT='/downloads/ad-'+MARKER


class PreManifestCleanupTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(':memory:')
        self.addCleanup(self.db.close)
        self.db.executescript("""
            CREATE TABLE job_operation_members(job_id INTEGER,operation_id INTEGER);
            CREATE TABLE acquisition_plans(plan_id INTEGER,job_id INTEGER,
                submission_marker TEXT,info_hash TEXT);
            CREATE TABLE torrent_submissions(plan_id INTEGER,state TEXT);
            CREATE TABLE sonarr_magnet_intents (
                event_id INTEGER PRIMARY KEY,job_id INTEGER,plan_id INTEGER,
                tvdb_episode INTEGER,info_hash TEXT,marker TEXT,
                api_major INTEGER,base_url TEXT,save_path TEXT,category TEXT,
                timeout_seconds INTEGER,inventory_json TEXT,state TEXT,
                created_at_ms INTEGER,updated_at_ms INTEGER
            );
            INSERT INTO job_operation_members VALUES(21,7);
        """)
        self.db.execute(
            "INSERT INTO sonarr_magnet_intents VALUES("
            "4,21,1,2,?,?,?,?,?,10,NULL,'UNCERTAIN',100,100)",
            (HASH,MARKER,4,'http://localhost:8080',ROOT,'anime'))
        self.db.commit()
        @contextmanager
        def connect():
            yield self.db
        self.client=Mock()
        self.client_factory=Mock(return_value=self.client)
        service=object.__new__(CancellationService)
        service.store=SimpleNamespace(queue=SimpleNamespace(connection=connect))
        service.queue=SimpleNamespace(now=lambda:700100)
        service.secrets=SimpleNamespace(qbittorrent_credentials=lambda:'credentials')
        service.client_factory=self.client_factory
        service._fence=lambda db=None:None
        self.service=service

    def observed(self,*,root=ROOT,tags=('ad-'+MARKER,),files=()):
        return Observation(HASH,'pausedDL',root,'anime',tags,False,files)

    def test_absent_after_timeout_retires_without_torrent_command(self):
        self.client.inspect.return_value=None
        with patch.object(CancellationService,'_empty_magnet_root',return_value=True):
            self.assertEqual(self.service._pre_manifest(7),({4},True))
        self.client.remove_empty_legacy_magnet.assert_not_called()

    def test_absent_before_timeout_waits_without_deleting(self):
        self.service.queue.now=lambda:500
        self.client.inspect.return_value=None
        with patch.object(CancellationService,'_empty_magnet_root',return_value=True):
            self.assertEqual(self.service._pre_manifest(7),(set(),False))
        self.client.remove_empty_legacy_magnet.assert_not_called()

    def test_owned_stopped_empty_magnet_is_removed_once(self):
        self.client.inspect.return_value=self.observed()
        self.client.remove_empty_legacy_magnet.return_value=True
        with patch.object(CancellationService,'_empty_magnet_root',return_value=True):
            self.assertEqual(self.service._pre_manifest(7),({4},True))
        self.client.remove_empty_legacy_magnet.assert_called_once()
        self.assertEqual(self.db.execute(
            'SELECT state FROM sonarr_magnet_intents').fetchone(),('REVIEW',))
        self.client.inspect.return_value=None
        with patch.object(CancellationService,'_empty_magnet_root',return_value=True):
            self.assertEqual(self.service._pre_manifest(7),({4},True))
        self.client.remove_empty_legacy_magnet.assert_called_once()

    def test_foreign_torrent_never_receives_remove_command(self):
        self.client.inspect.return_value=self.observed(tags=('ad-'+'d'*32,))
        with patch.object(CancellationService,'_empty_magnet_root',return_value=True):
            with self.assertRaises(CancellationError):
                self.service._pre_manifest(7)
        self.client.remove_empty_legacy_magnet.assert_not_called()
        self.assertEqual(self.db.execute(
            'SELECT state FROM sonarr_magnet_intents').fetchone(),('UNCERTAIN',))

    def test_unknown_local_files_never_receive_remove_command(self):
        self.client.inspect.return_value=self.observed()
        with patch.object(CancellationService,'_empty_magnet_root',return_value=False):
            with self.assertRaises(CancellationError):
                self.service._pre_manifest(7)
        self.client.remove_empty_legacy_magnet.assert_not_called()
