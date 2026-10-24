"""Offline SQLite v21->v22 Keep journal migration and rollback; not run."""
import sqlite3
import unittest

from src.nextgen.storage.migrations import SQL_DIR,SCRIPTS,_structure
from src.nextgen.storage.sqlite import initialize


class KeepImportMigrationTests(unittest.TestCase):
    def test_keep_journal_upgrade_matches_fresh_schema(self):
        old=sqlite3.connect(":memory:")
        fresh=sqlite3.connect(":memory:")
        try:
            for filename in SCRIPTS[:21]:
                old.executescript((SQL_DIR/filename).read_text())
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0],21)
            self.assertIsNone(old.execute("SELECT name FROM sqlite_master WHERE name='keep_imports'").fetchone())
            old.executescript((SQL_DIR/"022_keep_imports.sql").read_text())
            old.executescript((SQL_DIR/"023_missing_episode_searches.sql").read_text())
            initialize(fresh)
            self.assertEqual(old.execute("PRAGMA user_version").fetchone()[0],23)
            self.assertEqual(_structure(old),_structure(fresh))
            self.assertEqual(old.execute("PRAGMA foreign_key_check").fetchall(),[])
        finally:old.close();fresh.close()

    def test_guard_and_failed_statement_leave_old_schema_intact(self):
        for version in (20,21,22):
            db=sqlite3.connect(":memory:")
            try:
                for filename in SCRIPTS[:21]:
                    db.executescript((SQL_DIR/filename).read_text())
                db.execute("PRAGMA user_version="+str(version))
                sql=(SQL_DIR/"022_keep_imports.sql").read_text()
                if version==21:
                    sql=sql.replace("PRAGMA user_version=22;","SELECT * FROM no_table;\nPRAGMA user_version=22;")
                with self.assertRaises(sqlite3.Error):db.executescript(sql)
                db.rollback()
                self.assertEqual(db.execute("PRAGMA user_version").fetchone()[0],version)
                self.assertIsNone(db.execute("SELECT name FROM sqlite_master WHERE name='keep_imports'").fetchone())
            finally:db.close()


if __name__=="__main__":unittest.main()
