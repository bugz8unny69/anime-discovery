"""Offline verification of the separate one-time maintenance script."""
import importlib.util
import sqlite3
import tempfile
import unittest
from pathlib import Path

from anime_fresh_database import initialize

SCRIPT=Path(__file__).resolve().parents[2]/"fixes"/"migrate_pending_identity_notifications.py"
spec=importlib.util.spec_from_file_location("one_time_identity_migration",SCRIPT)
migration=importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class MigrationTests(unittest.TestCase):
    def test_dry_run_apply_idempotent_and_history_intact(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath=Path(tmp)/"data.sqlite"
            initialize(dbpath)
            with sqlite3.connect(dbpath,isolation_level=None) as db:
                nid=db.execute("""INSERT INTO notifications
                    (source,release_name,source_guid,info_hash,received_at,status)
                    VALUES ('autobrr','Example S01E10','old',?,123,'IDENTIFYING')""",
                    ("a"*40,)).lastrowid
                self.assertEqual(migration.migrate(db)["jobs_to_create"],1)
                self.assertEqual(db.execute("SELECT COUNT(*) FROM daemon_jobs").fetchone()[0],0)
                self.assertEqual(migration.migrate(db,apply=True)["jobs_created"],1)
                self.assertEqual(migration.migrate(db,apply=True)["jobs_created"],0)
                self.assertEqual(db.execute("SELECT status FROM notifications WHERE id=?",
                                            (nid,)).fetchone()[0],"IDENTIFYING")
                self.assertEqual(db.execute("SELECT COUNT(*) FROM notifications").fetchone()[0],1)
                self.assertEqual(db.execute("""SELECT COUNT(*) FROM daemon_jobs
                    WHERE kind='identity_resolution'""").fetchone()[0],1)

    def test_existing_dispatch_is_not_migrated(self):
        with tempfile.TemporaryDirectory() as tmp:
            dbpath=Path(tmp)/"data.sqlite"
            initialize(dbpath)
            with sqlite3.connect(dbpath,isolation_level=None) as db:
                sid=db.execute("""INSERT INTO series(source,external_id,title)
                    VALUES('tvdb','123','Example')""").lastrowid
                nid=db.execute("""INSERT INTO notifications
                    (source,release_name,source_guid,info_hash,received_at,status)
                    VALUES('autobrr','Example','old',?,123,'IDENTIFYING')""",
                    ("a"*40,)).lastrowid
                db.execute("""INSERT INTO episode_dispatch
                    (notification_id,series_id,season,episode)
                    VALUES(?,?,1,1)""",(nid,sid))
                self.assertEqual(migration.migrate(db,apply=True)["jobs_created"],0)


if __name__=="__main__":
    unittest.main()
