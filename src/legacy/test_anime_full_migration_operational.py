"""End-to-end offline migration with the observed V10 and controller schemas."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_full_migration import migrate

ATTEMPTS="""CREATE TABLE download_attempts (
id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL, season INTEGER NOT NULL,
episode INTEGER NOT NULL, torrent_hash TEXT NOT NULL UNIQUE,
release_title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'QUEUED',
progress REAL NOT NULL DEFAULT 0, last_progress_at TEXT,
created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"""

class FullOfflineMigrationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root=Path(tmp.name)
        self.controller=root/"controller.db"
        self.inbox=root/"inbox.db"
        self.verified=root/"verified.db"
        self.shadow=root/"shadow.db"
        self.queue=root/"v10.db"
        self.output=root/"output.db"
        with sqlite3.connect(self.controller) as db:
            db.execute("CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,title TEXT,status TEXT)")
            db.execute("CREATE TABLE episodes(series_id INTEGER,season INTEGER,episode INTEGER,status TEXT)")
            db.execute("INSERT INTO series VALUES(1,'tvdb','real','Real','DISCOVERED')")
            db.execute(ATTEMPTS)
            db.execute("INSERT INTO download_attempts(series_id,season,episode,torrent_hash,release_title) VALUES(1,1,2,'hash','release')")
        with sqlite3.connect(self.inbox) as db:
            db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY,source TEXT,release_name TEXT,source_guid TEXT,info_hash TEXT,received_at INTEGER,status TEXT)")
            db.execute("INSERT INTO notifications VALUES(11,'nyaa','release','guid','hash',100,'UNTRUSTED')")
        with sqlite3.connect(self.verified) as db:
            db.execute("""CREATE TABLE verified_series_identity(
                notification_id INTEGER PRIMARY KEY,anidb_id TEXT NOT NULL,tvdb_id TEXT NOT NULL,
                mapping_source TEXT NOT NULL,decision TEXT NOT NULL,
                episode_identity_verified INTEGER NOT NULL,eligible_for_acquisition INTEGER NOT NULL,
                evidence_json TEXT NOT NULL,evidence_sha256 TEXT NOT NULL,
                created_at TEXT NOT NULL,updated_at TEXT NOT NULL)""")
            db.execute("INSERT INTO verified_series_identity VALUES(11,'1','2','manual','REVIEW',0,0,'{}','digest','now','now')")
        with sqlite3.connect(self.shadow) as db:
            db.execute("CREATE TABLE confidence_shadow_v15(notification_id INTEGER PRIMARY KEY,evaluated_at REAL,policy_version TEXT,score INTEGER,decision TEXT,evidence_json TEXT)")
            db.execute("CREATE TABLE episode_verification_v16(notification_id INTEGER PRIMARY KEY,evaluated_at REAL,decision TEXT,verified INTEGER,evidence_json TEXT)")
            db.execute("INSERT INTO confidence_shadow_v15 VALUES(11,1.0,'v15',0,'REVIEW','{}')")
            db.execute("INSERT INTO episode_verification_v16 VALUES(11,1.0,'REVIEW',0,'{}')")
        with sqlite3.connect(self.queue) as db:
            db.execute("CREATE TABLE identity_queue(notification_id INTEGER PRIMARY KEY,last_action TEXT NOT NULL,attempts INTEGER NOT NULL,next_at REAL NOT NULL,updated_at REAL NOT NULL)")
            db.execute("INSERT INTO identity_queue VALUES(11,'RETRY',2,120.0,100.0)")

    def test_full_rehearsal_preserves_archives_and_evidence(self):
        result=migrate(self.controller,self.inbox,self.verified,self.shadow,self.output,identity_queue=self.queue)
        self.assertTrue(result["archive_audit"]["download_attempts"]["equal"])
        self.assertTrue(result["archive_audit"]["identity_queue_v10"]["equal"])
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute("SELECT attempts FROM legacy_identity_queue_v10").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT torrent_hash FROM legacy_download_attempts").fetchone()[0],"hash")
            self.assertEqual(db.execute("SELECT notification_id FROM verified_series_identity").fetchone()[0],11)
            self.assertEqual(db.execute("SELECT notification_id FROM confidence_shadow_v15").fetchone()[0],11)
            self.assertEqual(db.execute("SELECT notification_id FROM episode_verification_v16").fetchone()[0],11)

    def test_unrecognized_attempt_schema_removes_output(self):
        with sqlite3.connect(self.controller) as db:
            db.execute("ALTER TABLE download_attempts ADD COLUMN unknown TEXT")
        with self.assertRaises(ValueError):
            migrate(self.controller,self.inbox,self.verified,self.shadow,self.output,identity_queue=self.queue)
        self.assertFalse(self.output.exists())

if __name__=="__main__":
    unittest.main()
