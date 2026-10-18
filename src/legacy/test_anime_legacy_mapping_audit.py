import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_legacy_mapping_audit import validate_operational_mapping

class LegacyMappingAuditTests(unittest.TestCase):
    def test_unmapped_nonempty_history_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            src=Path(directory)/"source.db"
            dst=Path(directory)/"target.db"
            for path in (src,dst):
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE download_history(id INTEGER)")
            with sqlite3.connect(src) as db:
                db.execute("INSERT INTO download_history VALUES(7)")
            result=validate_operational_mapping(src,dst,{})
            self.assertFalse(result["all_verified"])
            self.assertIn("unmapped",result["results"][0]["reason"])
    def test_exact_rows_pass_review(self):
        with tempfile.TemporaryDirectory() as directory:
            src=Path(directory)/"source.db"
            dst=Path(directory)/"target.db"
            for path in (src,dst):
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE download_history(id INTEGER)")
                    db.execute("INSERT INTO download_history VALUES(7)")
            result=validate_operational_mapping(src,dst,{"download_history":"download_history"})
            self.assertTrue(result["all_verified"])
            self.assertFalse(result["writes_enabled"])

if __name__=="__main__":
    unittest.main()
