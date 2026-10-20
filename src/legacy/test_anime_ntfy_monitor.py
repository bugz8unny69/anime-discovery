"""NTFY reminder state is idempotent and stops when a review is approved."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_fresh_database import initialize
from anime_ntfy_monitor import check_once,mark_sent

class MonitorTests(unittest.TestCase):
    def test_reminders_are_gated_by_review_and_interval(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"db.sqlite"
            initialize(path)
            with sqlite3.connect(path,isolation_level=None) as db:
                db.execute("PRAGMA foreign_keys=ON")
                nid=db.execute("""INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at)
                    VALUES ('autobrr','Example S01E01','guid','aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa',1)""").lastrowid
                db.execute("UPDATE notifications SET status='NEEDS_REVIEW' WHERE id=?",(nid,))
                settings={"ntfy":{"enabled":True,"reminder_hours":2}}
                calls=[]
                def send(*args):
                    calls.append(args[2])
                    return True
                self.assertEqual(check_once(db,settings,{},now=10000,sender=send)["sent"],1)
                self.assertEqual(check_once(db,settings,{},now=10001,sender=send)["sent"],0)
                self.assertEqual(check_once(db,settings,{},now=17201,sender=send)["sent"],1)
                sid=db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb','123','Example')").lastrowid
                db.execute("INSERT INTO episode_dispatch(notification_id,series_id,season,episode,state) VALUES (?,?,1,1,'CLAIMED')",(nid,sid))
                self.assertEqual(check_once(db,settings,{},now=25000,sender=send)["sent"],0)
    def test_legacy_untrusted_row_is_backfilled_for_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"db.sqlite"
            initialize(path)
            with sqlite3.connect(path,isolation_level=None) as db:
                nid=db.execute("""INSERT INTO notifications
                    (source,release_name,source_guid,info_hash,received_at)
                    VALUES ('nyaa','Old unmatched','old-guid',?,1)""",
                    ("b"*40,)).lastrowid
                calls=[]
                settings={"ntfy":{"enabled":True,"reminder_hours":24}}
                result=check_once(db,settings,{},now=1000,
                    sender=lambda *_: calls.append(nid) or True)
                self.assertEqual(result["sent"],0)
                self.assertEqual(calls,[])
                self.assertEqual(db.execute("SELECT status FROM notifications WHERE id=?",
                    (nid,)).fetchone()[0],"UNTRUSTED")

    def test_disabled_no_schema_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"db.sqlite"
            initialize(path)
            with sqlite3.connect(path,isolation_level=None) as db:
                self.assertEqual(check_once(db,{"ntfy":{"enabled":False}}, {},now=1)["sent"],0)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='ntfy_delivery'").fetchone())

if __name__=="__main__":unittest.main()
