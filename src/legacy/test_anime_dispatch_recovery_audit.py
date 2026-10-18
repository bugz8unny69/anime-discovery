import sqlite3
import unittest
from anime_dispatch_recovery_audit import stale_claims

class RecoveryAuditTests(unittest.TestCase):
    def test_only_stale_claims_returned_without_mutation(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        try:
            db.execute("""CREATE TABLE episode_dispatch(
                notification_id INTEGER,series_id INTEGER,season INTEGER,
                episode INTEGER,state TEXT,attempts INTEGER,updated_at INTEGER)""")
            db.executemany("INSERT INTO episode_dispatch VALUES(?,?,?,?,?,?,?)",[
                (1,10,1,1,"CLAIMED",2,100),
                (2,10,1,2,"CLAIMED",1,900),
                (3,10,1,3,"READY",0,100)])
            self.assertEqual([x["notification_id"] for x in
                              stale_claims(db,older_than_seconds=100,now=500)],[1])
            self.assertEqual(db.execute("SELECT state FROM episode_dispatch WHERE notification_id=1").fetchone()[0],"CLAIMED")
        finally:
            db.close()

    def test_threshold_is_bounded(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        try:
            with self.assertRaises(ValueError):
                stale_claims(db,older_than_seconds=0)
        finally:
            db.close()

if __name__=="__main__":
    unittest.main()
