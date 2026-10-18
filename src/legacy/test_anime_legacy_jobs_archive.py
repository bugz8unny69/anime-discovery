import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_legacy_jobs_archive import archive_tables

class JobArchiveTests(unittest.TestCase):
    def test_archive_replay(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"source.db"
            target=Path(directory)/"target.db"
            with sqlite3.connect(source) as db:
                for name in ("episode_jobs","historical_candidates","historical_search_attempts","job_events","series_jobs"):
                    db.execute("CREATE TABLE "+name+" (id INTEGER, state TEXT)")
                    db.execute("INSERT INTO "+name+" VALUES (1,'PENDING')")
            with sqlite3.connect(target,isolation_level=None) as db:
                result=archive_tables(db,source,"jobs")
                self.assertEqual(sum(result["archived_rows"].values()),5)
                self.assertFalse(result["jobs_activated"])
                self.assertEqual(archive_tables(db,source,"jobs")["archived_rows"],result["archived_rows"])
                db.execute("UPDATE legacy_episode_jobs SET state='OTHER'")
                with self.assertRaises(ValueError):
                    archive_tables(db,source,"jobs")

if __name__=="__main__":
    unittest.main()
