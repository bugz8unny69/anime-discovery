"""Offline v22->v23 missing-episode inventory migration tests; unrun."""
import sqlite3
import unittest

from src.nextgen.storage.migrations import SQL_DIR,SCRIPTS,_structure
from src.nextgen.storage.sqlite import initialize


class MissingSearchMigrationTests(unittest.TestCase):
    def test_upgrade_matches_current_fresh_schema(self):
        historical=sqlite3.connect(":memory:")
        fresh=sqlite3.connect(":memory:")
        try:
            for path in SCRIPTS[:22]:historical.executescript((SQL_DIR/path).read_text())
            self.assertEqual(historical.execute("PRAGMA user_version").fetchone()[0],22)
            historical.executescript((SQL_DIR/"023_missing_episode_searches.sql").read_text())
            initialize(fresh)
            self.assertEqual(historical.execute("PRAGMA user_version").fetchone()[0],23)
            self.assertEqual(_structure(historical),_structure(fresh))
            self.assertEqual(historical.execute("PRAGMA foreign_key_check").fetchall(),[])
        finally:historical.close();fresh.close()

    def test_wrong_version_and_injected_failure_roll_back(self):
        for version in (21,22,23):
            db=sqlite3.connect(":memory:")
            try:
                for path in SCRIPTS[:22]:db.executescript((SQL_DIR/path).read_text())
                db.execute("PRAGMA user_version="+str(version))
                sql=(SQL_DIR/"023_missing_episode_searches.sql").read_text()
                if version==22:
                    sql=sql.replace("PRAGMA user_version=23;",
                        "SELECT * FROM missing_table;\nPRAGMA user_version=23;")
                with self.assertRaises(sqlite3.Error):db.executescript(sql)
                db.rollback()
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],version)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master "
                    "WHERE name='missing_episode_candidates'").fetchone())
            finally:db.close()


if __name__=="__main__":unittest.main()
