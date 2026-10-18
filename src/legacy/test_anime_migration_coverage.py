import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_migration_coverage import migration_coverage

class MigrationCoverageTests(unittest.TestCase):
    def test_unmigrated_queue_history_blocks_cutover(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[Path(directory)/f"{name}.db" for name in ("controller","inbox","verified","shadow","output")]
            for path in paths:
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE series(id INTEGER)")
                    db.execute("INSERT INTO series VALUES(1)")
            with sqlite3.connect(paths[0]) as db:
                db.execute("CREATE TABLE download_history(id INTEGER)")
                db.execute("INSERT INTO download_history VALUES(7)")
            report=migration_coverage(*paths)
            self.assertFalse(report["ready_for_cutover"])
            self.assertEqual(report["unresolved_operational"][0]["table"],"download_history")
    def test_missing_evidence_blocks_cutover(self):
        with tempfile.TemporaryDirectory() as directory:
            paths=[Path(directory)/f"{name}.db" for name in ("controller","inbox","verified","shadow","output")]
            for path in paths:
                with sqlite3.connect(path) as db:
                    db.execute("CREATE TABLE series(id INTEGER)")
            with sqlite3.connect(paths[2]) as db:
                db.execute("CREATE TABLE verified_series_identity(notification_id INTEGER)")
                db.execute("INSERT INTO verified_series_identity VALUES(7)")
            report=migration_coverage(*paths)
            self.assertIn("verified_series_identity",report["missing_evidence"])
            self.assertFalse(report["ready_for_cutover"])

if __name__=="__main__":
    unittest.main()
