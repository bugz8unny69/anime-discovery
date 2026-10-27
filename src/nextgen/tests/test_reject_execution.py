"""Offline verification of shared Reject proof selection and safe preflight."""
import json
import sqlite3
import unittest
from types import SimpleNamespace

from src.nextgen.jobs.reject_execution import _sources
from src.nextgen.jobs.reject_media_job import registration as single_registration
from src.nextgen.jobs.reject_batch_job import registration as batch_registration
from src.nextgen.storage.review_decisions import remove_selected
from src.nextgen.staging import StagingReview


class SharedRejectContractTests(unittest.TestCase):
    def test_registered_handlers_use_expected_media_scopes(self):
        single=single_registration()
        batch=batch_registration()
        self.assertEqual(single.kind,'REJECT_MEDIA')
        self.assertEqual(batch.kind,'REJECT_BATCH')
        self.assertTrue(callable(single.execute) and callable(single.persist))
        self.assertTrue(callable(batch.execute) and callable(batch.persist))

    def test_malformed_publication_receipts_are_rejected_without_touching_disk(self):
        entries=[{'role':'media','path':'episode.mkv'},
                 {'role':'episode','path':'episode.nfo'},
                 {'role':'series','path':'tvshow.nfo'}]
        plan=json.dumps({'root':'/tmp/reject-preflight-stage','entries':entries})
        for proofs in (
            [{'role':'media','path':'episode.mkv'}],
            [{'role':'media','path':'episode.mkv'},
             {'role':'episode','path':'WRONG.nfo'},
             {'role':'series','path':'tvshow.nfo'}],
            [{'role':'media','path':'episode.mkv'},
             {'role':'episode','path':'episode.nfo'},
             {'role':'series','path':'tvshow.nfo'},
             {'role':'media','path':'extra.mkv'}],
        ):
            calls=[]
            with self.subTest(proofs=proofs),self.assertRaises(StagingReview):
                remove_selected(plan,json.dumps(proofs),
                    lambda:calls.append('guard'),'/tmp/reject-preflight-keep')
            self.assertEqual(calls,[])

    def test_batch_scope_checks_all_episode_proofs_and_anime_identity(self):
        db=sqlite3.connect(':memory:')
        self.addCleanup(db.close)
        db.executescript("""
            CREATE TABLE job_operations(operation_id INTEGER,state TEXT,
                cleanup_state TEXT,reason_code TEXT);
            CREATE TABLE job_operation_members(operation_id INTEGER,job_id INTEGER);
            CREATE TABLE management_actions(operation_id INTEGER,action TEXT,
                target_job_id INTEGER,job_id INTEGER);
            CREATE TABLE anime_review_decisions(job_id INTEGER,operation_id INTEGER,
                anidb_id INTEGER,decision TEXT,cleanup_state TEXT);
            CREATE TABLE batch_staging_publications(plan_id INTEGER,file_index INTEGER,
                manifest_json TEXT,receipts_json TEXT,job_id INTEGER,state TEXT);
            CREATE TABLE batch_episode_reservations(plan_id INTEGER,file_index INTEGER,
                state TEXT,anidb_id INTEGER,anidb_episode_id INTEGER,
                tvdb_series_id INTEGER,tvdb_episode_id INTEGER,
                tvdb_season INTEGER,tvdb_episode INTEGER);
            CREATE TABLE batch_trial_files(plan_id INTEGER,file_index INTEGER);
            INSERT INTO job_operations VALUES(7,'STAGED','NONE',NULL);
            INSERT INTO job_operation_members VALUES(7,101),(7,301),(7,302);
            INSERT INTO management_actions VALUES(7,'REJECT',101,201);
            INSERT INTO anime_review_decisions VALUES(201,7,123,'REJECT','PENDING');
            INSERT INTO batch_staging_publications VALUES
                (10,1,'manifest1','receipts1',301,'PUBLISHED'),
                (10,2,'manifest2','receipts2',302,'PUBLISHED');
            INSERT INTO batch_episode_reservations VALUES
                (10,1,'ACTIVE',123,1,456,101,1,1),
                (10,2,'ACTIVE',123,2,456,102,1,2);
            INSERT INTO batch_trial_files VALUES(10,1),(10,2);
        """)
        queue=SimpleNamespace(_owns=lambda *args:None,now=lambda:1)
        actions=SimpleNamespace(queue=queue)
        claim=SimpleNamespace(job_id=201)
        sources,state=_sources(db,actions,claim,101,batch=True)
        self.assertEqual(sources,(('manifest1','receipts1'),
                                  ('manifest2','receipts2')))
        self.assertEqual(state,'PENDING')

        db.execute('UPDATE batch_episode_reservations SET anidb_id=999 '
                   'WHERE file_index=2')
        with self.assertRaises(StagingReview):
            _sources(db,actions,claim,101,batch=True)
        db.execute('UPDATE batch_episode_reservations SET anidb_id=123 '
                   'WHERE file_index=2')
        db.execute("UPDATE batch_staging_publications SET state='PLANNED' "
                   'WHERE file_index=2')
        # A partially staged season can never be rejected as a complete pack.
        from src.nextgen.sonarr import KeepReview
        with self.assertRaises(KeepReview):
            _sources(db,actions,claim,101,batch=True)
