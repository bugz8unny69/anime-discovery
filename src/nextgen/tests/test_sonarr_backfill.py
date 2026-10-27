"""Offline lease-fenced Sonarr backfill scheduling and observation tests."""
import sqlite3
import unittest

from src.nextgen.configuration import ConfigurationStore
from src.nextgen.job_contracts import Registry, Policy
from src.nextgen.jobs.evaluate_trial_job import registration as trial_registration
from src.nextgen.jobs.discover_sonarr_backfill_job import (
    registration as discovery_registration, KIND as DISCOVER_KIND,
)
from src.nextgen.acquisition.sonarr_search import BackfillObservation, SearchUnavailable
from src.nextgen.storage.migrations import SQL_DIR, SCRIPTS, _structure
from src.nextgen.storage.sqlite import connect, initialize
from src.nextgen.tests.test_trial_policy import TrialEvaluationTests
from src.nextgen.worker import Worker


class FakeDiscovery:
    def __init__(self):
        self.calls = []
        self.error = False

    def backfill(self, tvdb_series_id, season, numbers, *, reserved=(), verified_ids=None):
        self.calls.append((tvdb_series_id, season, numbers, tuple(reserved), dict(verified_ids or {})))
        if self.error: raise SearchUnavailable()
        return tuple(
            BackfillObservation(n, 200+n, 2000+n, 'IN_PROGRESS')
            if n in reserved else
            BackfillObservation(n, 200+n, 2000+n, 'CANDIDATES', 3, 2, 1)
            for n in numbers
        )


class BackfillWorkerTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = TrialEvaluationTests.asyncSetUp
    rows = TrialEvaluationTests.rows
    source = TrialEvaluationTests.source

    def worker(self, fake, *, enabled=True):
        trial = trial_registration(discovery_kind=DISCOVER_KIND if enabled else None)
        registrations = [trial]
        if enabled:
            registrations.append(discovery_registration(None,
                client_factory=lambda config, secrets: fake))
        worker = Worker(self.store, self.startup, Registry(registrations),
                        policy=Policy(lease_ms=30000))
        self.addAsyncCleanup(worker.close)
        return worker

    async def test_first_plan_creates_one_paged_discovery_chain_with_durable_results(self):
        self.source(10)
        fake = FakeDiscovery()
        worker = self.worker(fake)
        await worker.attempt()  # EVALUATE_TRIAL -> first DISCOVER job in same tx.
        self.assertEqual(self.rows(
            "SELECT kind,payload_json FROM jobs WHERE kind=?",(DISCOVER_KIND,)),
            [(DISCOVER_KIND,'{"plan_id": 1, "start": 1}')])
        await worker.attempt()  # E01–E04 -> E05–E06.
        await worker.attempt()
        self.assertEqual([row[0] for row in self.rows(
            "SELECT tvdb_episode FROM sonarr_backfill_results ORDER BY tvdb_episode")],
            [1,2,3,4,5,6])
        self.assertEqual(self.rows(
            "SELECT status,candidates,approved,exact FROM sonarr_backfill_results "
            "WHERE tvdb_episode=6"), [('CANDIDATES',3,2,1)])
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind=?",(DISCOVER_KIND,)),[(2,)])
        self.assertEqual([v[2] for v in fake.calls],[(1,2,3,4),(5,6)])
        self.source(11)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind=?",(DISCOVER_KIND,)),[(2,)])
        self.assertEqual(self.rows("SELECT count(*) FROM sonarr_backfill_results"),[(6,)])
        self.assertEqual(self.rows(
            "SELECT count(*) FROM jobs WHERE kind IN "
            "('SUBMIT_TORRENT','RESERVE_EPISODE','DOWNLOAD_TORRENT')"),[(0,)])

    async def test_opt_in_off_means_no_new_discovery_jobs(self):
        self.source(10)
        worker = self.worker(FakeDiscovery(),enabled=False)
        await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind=?",(DISCOVER_KIND,)),[(0,)])

    async def test_zero_backfill_count_creates_no_discovery_work(self):
        self.store.update({'trial':{'backfill_count':0,'following_count':2}},
                          expected_revision=1)
        self.source(10)
        worker = self.worker(FakeDiscovery())
        await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind=?",(DISCOVER_KIND,)),[(0,)])

    async def test_unavailable_sonarr_retries_without_persisting_a_partial_page(self):
        self.source(10)
        fake = FakeDiscovery()
        fake.error = True
        worker = self.worker(fake)
        await worker.attempt()
        await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM sonarr_backfill_results"),[(0,)])
        self.assertEqual(self.rows(
            "SELECT state,last_reason_code FROM jobs WHERE kind=?",(DISCOVER_KIND,)),
            [('RETRY_WAIT','SONARR_DISCOVERY_UNAVAILABLE')])
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind=?",(DISCOVER_KIND,)),[(1,)])



class BackfillSchemaTests(unittest.TestCase):
    def test_explicit_v41_to_v43_and_fresh_schema_match(self):
        old = sqlite3.connect(':memory:')
        fresh = sqlite3.connect(':memory:')
        try:
            for script in SCRIPTS[:41]:
                old.executescript((SQL_DIR/script).read_text())
            old.execute("INSERT INTO incoming_events(source,raw_body,received_at_ms) "
                        "VALUES('test',X'61',1)")
            old.commit()
            before = old.execute('SELECT * FROM incoming_events').fetchall()
            old.executescript((SQL_DIR/'042_sonarr_backfill.sql').read_text())
            old.executescript((SQL_DIR/'043_sonarr_selection.sql').read_text())
            initialize(fresh)
            self.assertEqual(_structure(old),_structure(fresh))
            self.assertEqual(old.execute('SELECT * FROM incoming_events').fetchall(),before)
            self.assertEqual(old.execute('PRAGMA user_version').fetchone()[0],43)
        finally:
            old.close()
            fresh.close()

    def test_v43_allows_local_candidates_even_when_sonarr_approved_zero(self):
        db = sqlite3.connect(':memory:')
        try:
            initialize(db)
            sql = db.execute("SELECT sql FROM sqlite_master WHERE name='sonarr_backfill_results'").fetchone()[0]
            self.assertIn('exact BETWEEN 0 AND candidates', sql)
            self.assertNotIn('exact BETWEEN 0 AND approved', sql)
        finally:
            db.close()

    def test_wrong_starting_version_rolls_back(self):
        db = sqlite3.connect(':memory:')
        try:
            db.execute('PRAGMA user_version=40')
            with self.assertRaises(sqlite3.Error):
                db.executescript((SQL_DIR/'042_sonarr_backfill.sql').read_text())
            db.rollback()
            self.assertEqual(db.execute('PRAGMA user_version').fetchone()[0],40)
            self.assertIsNone(db.execute(
                "SELECT name FROM sqlite_master WHERE name='sonarr_backfill_results'").fetchone())
        finally:
            db.close()
