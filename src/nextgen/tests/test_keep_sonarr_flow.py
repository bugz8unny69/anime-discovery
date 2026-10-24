"""Offline exact Sonarr Keep journal and import tests. Not run under project policy."""
import json
from pathlib import Path
import shutil
import unittest
from unittest.mock import patch

from src.nextgen.jobs.keep_media_job import registration as keep
from src.nextgen.sonarr import SonarrUnavailable
from src.nextgen.storage.management_actions import ManagementActions
from src.nextgen.storage.sqlite import connect, transaction
from src.nextgen.tests.test_stage_media_job import StageMediaJobTests
from src.nextgen.tests.test_acquisition_preparation import AcquisitionPreparationTests


class Secrets:
    def sonarr_api_key(self):return "test-private-api-key"


class SonarrDouble:
    def __init__(self,library,identity,*,lose_response=False,wrong_copy=False):
        self.library=library
        self.identity=identity
        self.sent=0
        self.imported=False
        self.lose_response=lose_response
        self.wrong_copy=wrong_copy
        self.command=907
        self.file=library/"Series"/"Season 01"/"S01E01.mkv"

    def ensure_series(self,tvdb):
        assert tvdb==self.identity[0]
        return 88,False

    def inventory(self,sonarr_id):
        assert sonarr_id==88
        series,season,number,tvdb_episode=self.identity
        episodes=[{"id":91,"seasonNumber":season,"episodeNumber":number,
                   "tvdbId":tvdb_episode,"episodeFileId":501 if self.imported else 0,
                   "hasFile":self.imported}]
        files=[{"id":501,"seriesId":88,"path":str(self.file)}] if self.imported else []
        return episodes,files

    def manual_import_preview(self,sonarr_id,items):
        assert sonarr_id==88
        item=items[0]
        assert (item["season"],item["episode"],item["tvdb_episode_id"])==self.identity[1:]
        return [{"path":item["path"],"seriesId":88,"episodeIds":[91],
                 "quality":{"quality":{"id":7}},"languages":[{"id":1}]}]

    def submit_copy(self,selected):
        self.sent+=1
        if self.lose_response:raise SonarrUnavailable()
        self.file.parent.mkdir(parents=True,exist_ok=True)
        if self.wrong_copy:self.file.write_bytes(b"wrong content")
        else:shutil.copyfile(selected[0]["path"],self.file)
        self.imported=True
        return self.command

    def command_status(self,command_id):
        assert command_id==self.command
        return "completed"


class KeepFlowTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp=AcquisitionPreparationTests.asyncSetUp
    rows=AcquisitionPreparationTests.rows
    ready=StageMediaJobTests.ready
    queued=StageMediaJobTests.queued
    due=StageMediaJobTests.due
    source=StageMediaJobTests.source
    worker=StageMediaJobTests.worker
    staged_ready=StageMediaJobTests.staged_ready

    async def setup_stage(self):
        worker=self.worker(additional=(keep(Secrets()),))
        self.addAsyncCleanup(worker.close)
        stage,_=await self.staged_ready(worker)
        await worker.attempt()
        assert self.rows("SELECT state FROM staging_publications")==[("PUBLISHED",)]
        job=self.rows("SELECT job_id FROM jobs WHERE kind='STAGE_TRIAL_MEDIA'")[0][0]
        library=self.root/"library";library.mkdir()
        self.store.update({"storage":{"keep_root":str(library)},
                           "sonarr":{"base_url":"https://sonarr.arr.internal",
                                     "root_folder":str(library),"quality_profile_name":"Anime"}},
                          expected_revision=4)
        identity=self.rows("SELECT tvdb_series_id,tvdb_season,tvdb_episode,tvdb_episode_id FROM episode_reservations")[0]
        return worker,stage,job,library,identity

    async def test_keep_snapshots_staging_identity_and_completes_only_after_copy_proof(self):
        worker,stage,job,library,identity=await self.setup_stage()
        actions=ManagementActions(self.database)
        status,data,_=actions.submit(job,"keep")
        self.assertEqual(status,202)
        self.assertTrue(data["execution_available"])
        journal=self.rows("SELECT approval_json,phase FROM keep_imports")[0]
        saved=json.loads(journal[0])
        self.assertEqual(journal[1],"APPROVED")
        self.assertEqual(saved["identity"]["tvdb_series_id"],identity[0])
        self.assertEqual(saved["identity"]["tvdb_episode_id"],identity[3])
        self.assertEqual(actions.submit(job,"keep")[1]["job_id"],data["job_id"])
        fake=SonarrDouble(library,identity)
        with patch("src.nextgen.jobs.keep_media_job.SonarrClient",return_value=fake):
            await worker.attempt()
        self.assertEqual(fake.sent,1)
        self.assertEqual(self.rows("SELECT phase FROM keep_imports"),[("VERIFIED",)])
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE job_id=?",(data["job_id"],)),[("DONE",)])
        self.assertEqual(len(list(stage.rglob("*.mkv"))),1)
        self.assertTrue(fake.file.is_file())

    async def test_lost_command_response_remains_uncertain_and_never_reposts(self):
        worker,stage,job,library,identity=await self.setup_stage()
        actions=ManagementActions(self.database)
        _,data,_=actions.submit(job,"keep")
        fake=SonarrDouble(library,identity,lose_response=True)
        with patch("src.nextgen.jobs.keep_media_job.SonarrClient",return_value=fake):
            await worker.attempt()
        self.assertEqual(fake.sent,1)
        self.assertEqual(self.rows("SELECT phase FROM keep_imports"),[("IMPORT_INTENT",)])
        self.assertEqual(self.rows("SELECT last_reason_code FROM jobs WHERE job_id=?",(data["job_id"],)),
                         [("KEEP_COMMAND_UNCERTAIN",)])
        self.assertNotIn("resumed",actions.submit(job,"keep")[1])
        # Simulate recovery/reclaim without authorizing a second remote POST.
        db=connect(self.database)
        try:
            with transaction(db):
                db.execute("UPDATE jobs SET state='PENDING',available_at_ms=0 WHERE job_id=?",(data["job_id"],))
        finally:db.close()
        with patch("src.nextgen.jobs.keep_media_job.SonarrClient",return_value=fake):
            await worker.attempt()
        self.assertEqual(fake.sent,1)
        self.assertEqual(self.rows("SELECT phase FROM keep_imports"),[("IMPORT_INTENT",)])
        self.assertEqual(len(list(stage.rglob("*.mkv"))),1)

    async def test_mismatching_permanent_file_never_counts_as_kept(self):
        worker,stage,job,library,identity=await self.setup_stage()
        _,data,_=ManagementActions(self.database).submit(job,"keep")
        fake=SonarrDouble(library,identity,wrong_copy=True)
        with patch("src.nextgen.jobs.keep_media_job.SonarrClient",return_value=fake):
            await worker.attempt()
        self.assertEqual(self.rows("SELECT phase FROM keep_imports"),[("COMMAND_ACCEPTED",)])
        self.assertEqual(self.rows("SELECT state FROM jobs WHERE job_id=?",(data["job_id"],)),
                         [("NEEDS_REVIEW",)])
        self.assertEqual(len(list(stage.rglob("*.mkv"))),1)
        self.assertEqual(fake.sent,1)


if __name__=="__main__":unittest.main()
