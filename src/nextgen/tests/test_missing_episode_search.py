"""Offline missing-episode search coverage; intentionally unexecuted."""
import unittest
from src.nextgen.job_contracts import Registry
from src.nextgen.jobs.evaluate_trial_job import registration as evaluate
from src.nextgen.jobs.reserve_episode_job import registration as reserve
from src.nextgen.jobs.discover_missing_episodes_job import registration as discover
from src.nextgen.storage.sqlite import connect
from src.nextgen.tests.test_acquisition_preparation import AcquisitionPreparationTests
from src.nextgen.worker import Worker


class Secrets:
    def prowlarr_api_key(self):return "private-prowlarr-token"


class DummySearch:
    calls=[]
    def __init__(self,options):
        assert options.base_url=="https://prowlarr.internal"
        assert options.api_key=="private-prowlarr-token"
    def search(self,title,season,episode):
        type(self).calls.append((title,season,episode))
        return ()


class SearchWindowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=AcquisitionPreparationTests.asyncSetUp
    rows=AcquisitionPreparationTests.rows
    source=AcquisitionPreparationTests.source

    def worker(self):
        worker=Worker(self.store,self.startup,Registry((
            evaluate(reservation_kind="RESERVE_EPISODE",discovery_kind="DISCOVER_MISSING_EPISODES"),
            reserve(),
            discover(Secrets(),client_factory=DummySearch))))
        self.addAsyncCleanup(worker.close)
        return worker

    async def test_frozen_window_searches_uncovered_positions_only(self):
        self.store.update({"prowlarr":{"base_url":"https://prowlarr.internal"}},expected_revision=1)
        DummySearch.calls=[]
        self.source(episode=10)
        worker=self.worker()
        await worker.attempt()  # Evaluation commits both successors.
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind='DISCOVER_MISSING_EPISODES'"),[(1,)])
        await worker.attempt()  # Reserve received episode.
        await worker.attempt()  # Search six backfill positions.
        self.assertEqual([x[2] for x in DummySearch.calls],[1,2,3,4,5,6])
        self.assertEqual(self.rows("SELECT tvdb_episode,status FROM missing_episode_searches ORDER BY tvdb_episode"),
                         [(n,"NO_MATCH") for n in range(1,7)])
        self.assertEqual(self.rows("SELECT count(*) FROM missing_episode_candidates"),[(0,)])
        self.assertEqual(self.rows("SELECT count(*) FROM incoming_events"),[(1,)])
        self.assertEqual(self.rows("SELECT count(*) FROM acquisition_plans"),[(0,)])
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE kind='DISCOVER_MISSING_EPISODES'"),[("DONE",)])

    async def test_unconfigured_discovery_creates_no_search_jobs(self):
        self.source(episode=10)
        worker=self.worker()
        await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM jobs WHERE kind='DISCOVER_MISSING_EPISODES'"),[(0,)])

    async def test_duplicate_evaluation_does_not_duplicate_searched_targets(self):
        self.store.update({"prowlarr":{"base_url":"https://prowlarr.internal"}},expected_revision=1)
        DummySearch.calls=[]
        self.source(episode=10)
        worker=self.worker()
        for _ in range(3):await worker.attempt()
        self.source(episode=11)  # Same frozen plan; not selected.
        for _ in range(3):await worker.attempt()
        self.assertEqual(self.rows("SELECT count(*) FROM missing_episode_searches"),[(6,)])
        self.assertEqual(len(DummySearch.calls),6)


if __name__=="__main__":unittest.main()
