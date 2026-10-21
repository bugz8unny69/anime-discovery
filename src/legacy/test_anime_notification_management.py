import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_notification_management import delete_unmatched
from anime_dashboard_queries import all_jobs

class NotificationManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        path=Path(self.temp.name)/"test.sqlite"
        initialize(path)
        self.db=sqlite3.connect(path,isolation_level=None)
        self.db.execute("PRAGMA foreign_keys=ON")
        self.addCleanup(self.db.close)
        self.nid=self.db.execute("""INSERT INTO notifications
        (source,release_name,source_guid,info_hash,received_at,status)
        VALUES ('nyaa','Anime - 02','g123',?,1,'NEEDS_REVIEW')""",
        ("a"*40,)).lastrowid

    def test_unmatched_row_has_id_and_actions(self):
        item=all_jobs(self.db)["items"][0]
        self.assertEqual(item["id"],self.nid)
        self.assertTrue(item["can_resolve"])
        self.assertNotIn("can_delete",item)

    def test_delete_unmatched_and_ntfy_metadata(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS ntfy_delivery
            (notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
             sent_at INTEGER NOT NULL)""")
        self.db.execute("INSERT INTO ntfy_delivery VALUES (?,1)",(self.nid,))
        self.assertTrue(delete_unmatched(self.db,self.nid)["deleted"])
        self.assertIsNone(self.db.execute("SELECT 1 FROM notifications WHERE id=?",
                                          (self.nid,)).fetchone())
        self.assertIsNone(self.db.execute("SELECT 1 FROM ntfy_delivery WHERE notification_id=?",
                                          (self.nid,)).fetchone())

    def test_refuses_related_acquisition_job(self):
        self.db.execute("""INSERT INTO daemon_jobs(kind,subject_key,payload_json,state)
            VALUES ('claimed_acquisition',?,'{}','READY')""",(str(self.nid),))
        with self.assertRaises(ValueError):
            delete_unmatched(self.db,self.nid)
        self.assertIsNotNone(self.db.execute("SELECT 1 FROM notifications WHERE id=?",
                                              (self.nid,)).fetchone())

    def test_refuses_unexpected_related_records(self):
        self.db.execute("""CREATE TABLE guard(id INTEGER PRIMARY KEY,
          notification_id INTEGER REFERENCES notifications(id))""")
        self.db.execute("INSERT INTO guard(notification_id) VALUES (?)",(self.nid,))
        with self.assertRaises(ValueError):
            delete_unmatched(self.db,self.nid)

if __name__=="__main__":unittest.main()
