import sqlite3
import unittest
from unittest.mock import patch
from anime_dispatch_audit import audit_claimed

class DispatchAuditTests(unittest.TestCase):
    def test_verified_claim_requires_infohash(self):
        db=sqlite3.connect(":memory:",isolation_level=None)
        try:
            db.execute("CREATE TABLE notifications(id INTEGER PRIMARY KEY,info_hash TEXT)")
            db.execute("INSERT INTO notifications VALUES(1,?)",("a"*40,))
            approval={"series_id":4,"season":1,"episode":2}
            with patch("anime_dispatch_audit.approved_dispatch",return_value=approval):
                result=audit_claimed(db,1)
                self.assertTrue(result["authorized"])
                self.assertEqual(result["infohash"],"a"*40)
                db.execute("UPDATE notifications SET info_hash='bad' WHERE id=1")
                self.assertFalse(audit_claimed(db,1)["authorized"])
            with patch("anime_dispatch_audit.approved_dispatch",side_effect=ValueError("blocked")):
                self.assertFalse(audit_claimed(db,1)["authorized"])
        finally:
            db.close()

if __name__=="__main__":
    unittest.main()
