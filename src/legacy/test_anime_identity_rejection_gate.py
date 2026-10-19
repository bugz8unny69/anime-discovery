import sqlite3
import unittest
from anime_identity_rejection_gate import resolve_notification, acquisition_authorized, IdentityNotReady, SeriesBlocked

class GateTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.addCleanup(self.db.close)
        self.db.executescript("""
        CREATE TABLE notifications(id INTEGER PRIMARY KEY,status TEXT);
        CREATE TABLE verified_series_identity(notification_id INTEGER PRIMARY KEY,tvdb_id TEXT,episode_identity_verified INTEGER,eligible_for_acquisition INTEGER);
        CREATE TABLE series(id INTEGER PRIMARY KEY,source TEXT,external_id TEXT,status TEXT);
        CREATE TABLE migration_quarantined_series(series_id INTEGER PRIMARY KEY);
        CREATE TABLE series_quarantine(series_id INTEGER PRIMARY KEY);
        CREATE TABLE series_rejection_blocks(series_id INTEGER PRIMARY KEY);
        INSERT INTO notifications VALUES(7,'UNTRUSTED');
        INSERT INTO verified_series_identity VALUES(7,'123',0,0);
        INSERT INTO series VALUES(4,'tvdb','123','DISCOVERED');
        """)

    def test_resolution_does_not_authorize_download(self):
        self.assertEqual(resolve_notification(self.db,7),4)
        self.assertFalse(acquisition_authorized(self.db,7))

    def test_rejection_persists_across_hashes(self):
        self.db.execute("INSERT INTO series_rejection_blocks VALUES(4)")
        with self.assertRaises(SeriesBlocked):
            resolve_notification(self.db,7)
        self.db.execute("INSERT INTO notifications VALUES(8,'UNTRUSTED')")
        self.db.execute("INSERT INTO verified_series_identity VALUES(8,'123',0,0)")
        with self.assertRaises(SeriesBlocked):
            resolve_notification(self.db,8)

    def test_unknown_identity_fails_closed(self):
        self.db.execute("DELETE FROM verified_series_identity")
        with self.assertRaises(IdentityNotReady):
            resolve_notification(self.db,7)

    def test_quarantine_fails_closed(self):
        self.db.execute("INSERT INTO migration_quarantined_series VALUES(4)")
        with self.assertRaises(SeriesBlocked):
            resolve_notification(self.db,7)

    def test_canonical_quarantine_fails_closed(self):
        self.db.execute("INSERT INTO series_quarantine VALUES(4)")
        with self.assertRaises(SeriesBlocked):
            resolve_notification(self.db,7)

    def test_rejected_legacy_status_fails_closed(self):
        self.db.execute("UPDATE series SET status='REJECTED'")
        with self.assertRaises(SeriesBlocked):
            resolve_notification(self.db,7)

if __name__=="__main__":
    unittest.main()
