"""Reset only a selected series, replaying verified stored Autobrr notifications."""
import hashlib
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_acquisition_reset import reset_acquisitions
from anime_fresh_database import initialize
from anime_job_management import ensure_schema as ensure_admin
from anime_qb_ownership import ensure_schema as ensure_qb
from anime_webhook_processing import receive


class AcquisitionResetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.download=root/"torrents";self.download.mkdir()
        self.trial=root/"Anime-Trial";self.trial.mkdir()
        self.path=root/"db.sqlite"
        initialize(self.path)
        self.db=sqlite3.connect(self.path,isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)
        self.ids=[]
        self.paths=[]
        for ep in (1,2):
            hashval=("%x"%ep)*40
            result=receive(self.db,{"source":"autobrr",
                "source_guid":"solo-"+str(ep),
                "release_name":"Solo Leveling S01E%02d"%ep,
                "info_hash":hashval,"tvdb_id":389597,"anidb_id":123,
                "season":1,"episode":ep})
            nid=result["notification_id"]
            self.ids.append(nid)
            torrent=self.download/("S01E%02d.mkv"%ep)
            torrent.write_bytes(("source-"+str(ep)).encode())
            stage=self.trial/"TVDB-389597-S1"/"Season 01"/("S01E%02d.mkv"%ep)
            stage.parent.mkdir(parents=True,exist_ok=True)
            stage.write_bytes(torrent.read_bytes())
            self.paths.append(stage)
            digest=hashlib.sha256(stage.read_bytes()).hexdigest()
            self.db.execute("""INSERT INTO torrent_recovery_records
                (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
                VALUES (?,?,?,?,?,1)""",
                (nid,hashval,"magnet:?xt=urn:btih:"+hashval,str(stage),digest))
            self.db.execute("UPDATE episode_dispatch SET state='DONE' WHERE notification_id=?",(nid,))
            self.db.execute("UPDATE episodes SET status='STAGED' WHERE season=1 AND episode=?",(ep,))
            self.db.execute("""UPDATE daemon_jobs SET state='DONE',attempts=?
                WHERE kind='claimed_acquisition' AND subject_key=?""",(8+ep,str(nid)))
        self.sid=self.db.execute("SELECT id FROM series WHERE external_id='389597'").fetchone()[0]
        ensure_qb(self.db)
        self.db.execute("""INSERT INTO qb_torrent_ownership VALUES
            (?,?,NULL,'anime-discovery',123)""",("1"*40,"EXTERNAL"))
        ensure_admin(self.db)
        self.db.execute("""INSERT INTO daemon_job_admin_events
            (job_id,action,previous_state,previous_attempts,previous_error,created_at)
            VALUES (1,'retry','DEFERRED',9,'IdentityNotReady',123)""")
        (self.trial/"untracked.mkv").write_bytes(b"keep untracked")
        self.before={
            r[0]:r[1] for r in self.db.execute(
                "SELECT subject_key,payload_json FROM daemon_jobs WHERE kind='claimed_acquisition'")}
        self.oldids=[r[0] for r in self.db.execute(
            "SELECT id FROM daemon_jobs ORDER BY id")]

    def test_reset_recreates_only_series_jobs_and_retains_verified_identity(self):
        result=reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertEqual(result["removed_completed_jobs"],2)
        self.assertEqual(result["requeued_jobs"],2)
        self.assertEqual(result["removed_staged_files"],2)
        self.assertEqual(result["notifications_reused"],self.ids)
        jobs=self.db.execute("""SELECT id,subject_key,payload_json,state,attempts
            FROM daemon_jobs ORDER BY id""").fetchall()
        self.assertEqual(len(jobs),2)
        self.assertTrue(all(r[3:] == ("READY",0) for r in jobs))
        self.assertEqual({j[1]:j[2] for j in jobs},self.before)
        self.assertTrue(all(j[0] not in self.oldids for j in jobs))
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM torrent_recovery_records").fetchone()[0],0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM verified_series_identity").fetchone()[0],2)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM episode_approval_queue").fetchone()[0],2)
        self.assertEqual([r[0] for r in self.db.execute(
            "SELECT state FROM episode_dispatch ORDER BY notification_id")],
            ["CLAIMED","CLAIMED"])
        self.assertTrue(all(not p.exists() for p in self.paths))
        self.assertEqual(len(list(self.download.glob("*.mkv"))),2)
        self.assertTrue((self.trial/"untracked.mkv").exists())
        self.assertEqual(self.db.execute(
            "SELECT status FROM qb_torrent_ownership WHERE infohash=?",
            ("1"*40,)).fetchone()[0],"EXTERNAL")
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM daemon_job_admin_events").fetchone()[0],0)
        self.assertEqual(self.db.execute(
            "SELECT COUNT(*) FROM series_acquisition_resets").fetchone()[0],1)
        self.assertEqual(self.db.execute("PRAGMA foreign_key_check").fetchall(),[])

    def test_refuses_second_reset_and_keeps_new_ready_jobs(self):
        reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        with self.assertRaisesRegex(ValueError,"Only fully completed"):
            reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertEqual(self.db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0],2)

    def test_missing_old_media_allows_repair_after_manual_cleanup(self):
        self.paths[0].unlink()
        from anime_dashboard_queries import staged_series
        listing=staged_series(self.db)["items"]
        self.assertEqual(len(listing),1)
        self.assertEqual(listing[0]["staged_episodes"],1)
        self.assertEqual(listing[0]["missing_staged_episodes"],1)
        result=reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertEqual(result["removed_staged_files"],1)
        self.assertEqual(self.db.execute("SELECT count(*) FROM daemon_jobs WHERE state='READY'").fetchone()[0],2)

    def test_rejects_changed_staged_media_and_preserves_job_history(self):
        self.paths[1].write_bytes(b"not verified original")
        with self.assertRaisesRegex(ValueError,"changed since verification"):
            reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertTrue(self.paths[0].exists())
        self.assertEqual(self.db.execute(
            "SELECT count(*) FROM daemon_jobs WHERE state='DONE'").fetchone()[0],2)

    def test_rejects_active_job_or_pending_sonarr(self):
        self.db.execute("UPDATE daemon_jobs SET state='LEASED',lease_token='active' WHERE id=?",(self.oldids[0],))
        with self.assertRaisesRegex(ValueError,"fully completed"):
            reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertTrue(self.paths[0].exists())
        self.db.execute("UPDATE daemon_jobs SET state='DONE',lease_token=NULL WHERE id=?",(self.oldids[0],))
        self.db.execute("UPDATE series SET status='SONARR_IMPORT_PENDING' WHERE id=?",(self.sid,))
        with self.assertRaisesRegex(ValueError,"Kept, importing"):
            reset_acquisitions(self.db,self.sid,trial_root=self.trial)

    def test_wrong_or_shared_media_path_fails_without_deletion(self):
        other=self.download/"S01E01.mkv"
        self.db.execute("UPDATE torrent_recovery_records SET staged_path=? WHERE notification_id=?",
                        (str(other),self.ids[0]))
        with self.assertRaisesRegex(ValueError,"named series/season"):
            reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertTrue(other.exists())
        self.assertTrue(self.paths[1].exists())

    def test_reset_does_not_affect_another_series_job(self):
        extra=receive(self.db,{"source":"autobrr","source_guid":"other",
            "release_name":"Other Show S01E01","info_hash":"b"*40,
            "tvdb_id":99999,"anidb_id":234,"season":1,"episode":1})
        result=reset_acquisitions(self.db,self.sid,trial_root=self.trial)
        self.assertEqual(result["requeued_jobs"],2)
        self.assertEqual(self.db.execute("SELECT state FROM daemon_jobs WHERE subject_key=?",
            (str(extra["notification_id"]),)).fetchone()[0],"READY")

if __name__=="__main__":
    unittest.main()
