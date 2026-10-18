import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_legacy_schema_report import operational_schema_report

class LegacySchemaReportTests(unittest.TestCase):
    def test_reports_queue_constraints_without_modifying_source(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"legacy.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE series(id INTEGER PRIMARY KEY)")
                db.execute("""CREATE TABLE download_history(
                    id INTEGER PRIMARY KEY, series_id INTEGER NOT NULL,
                    status TEXT, FOREIGN KEY(series_id) REFERENCES series(id))""")
                db.execute("CREATE UNIQUE INDEX history_status ON download_history(status)")
                db.execute("INSERT INTO series VALUES(4)")
                db.execute("INSERT INTO download_history VALUES(7,4,'queued')")
            result=operational_schema_report(path)
            self.assertFalse(result["mapping_verified"])
            self.assertEqual(len(result["tables"]),1)
            table=result["tables"][0]
            self.assertEqual(table["table"],"download_history")
            self.assertEqual(table["rows"],1)
            self.assertEqual(table["foreign_keys"][0]["references_table"],"series")
            self.assertTrue(any(index["unique"] for index in table["indexes"]))
            with sqlite3.connect(path) as db:
                self.assertEqual(db.execute("SELECT status FROM download_history").fetchone()[0],"queued")

    def test_rejects_missing_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError,"snapshot"):
                operational_schema_report(Path(directory)/"missing.db")

if __name__=="__main__":
    unittest.main()
