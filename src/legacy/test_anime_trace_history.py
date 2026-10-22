import sqlite3
import unittest
from anime_trace_history import record,history,for_notification,trace_for_job

class TraceTests(unittest.TestCase):
    def test_durable_order_and_no_raw_data(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        record(db,for_notification(8),"HOOK_STARTED",job_id=2,
               notification_id=8,stage="identity",hook="verify")
        record(db,for_notification(8),"HOOK_FINISHED",job_id=2,
               notification_id=8,stage="identity",hook="verify",outcome="CONTINUE")
        self.assertEqual([e["event"] for e in history(db,"AD-8")],
                         ["HOOK_STARTED","HOOK_FINISHED"])
        self.assertEqual(history(db,"AD-9"),[])

    def test_acquisition_uses_original_notification_trace(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY)")
        db.execute("INSERT INTO notifications(id) VALUES(8)")
        trace,nid=trace_for_job(db,{"id":12,"kind":"claimed_acquisition","subject_key":"8"})
        self.assertEqual((trace,nid),("AD-8",8))
        trace,nid=trace_for_job(db,{"id":13,"kind":"series_gap_search","subject_key":"manual"})
        self.assertEqual((trace,nid),("AJ-13",None))

    def test_reject_untrusted_values(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        with self.assertRaises(ValueError):
            record(db,"AD-8","EVENT",hook="secret=abc with spaces")
