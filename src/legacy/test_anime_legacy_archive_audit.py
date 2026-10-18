import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_legacy_archive_audit import reconcile_archive

class ArchiveAuditTests(unittest.TestCase):
    def test_renamed_queue_reconciliation(self):
        with tempfile.TemporaryDirectory() as tmp:
            source,target=Path(tmp)/"a.db",Path(tmp)/"b.db"
            for path,name in ((source,"identity_queue"),(target,"legacy_identity_queue_v10")):
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE "+name+" (notification_id INTEGER PRIMARY KEY, attempts INTEGER)")
                    db.execute("INSERT INTO "+name+" VALUES (5,2)")
            self.assertTrue(reconcile_archive(source,target,"identity_queue","legacy_identity_queue_v10")["equal"])
            with sqlite3.connect(target) as db:
                db.execute("UPDATE legacy_identity_queue_v10 SET attempts=3")
            self.assertFalse(reconcile_archive(source,target,"identity_queue","legacy_identity_queue_v10")["equal"])

if __name__=="__main__":
    unittest.main()
