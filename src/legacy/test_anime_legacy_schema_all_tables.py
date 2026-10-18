import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from anime_legacy_schema_cli import main

class ExhaustiveSchemaTests(unittest.TestCase):
    def test_all_tables_includes_unrecognized_names_without_row_values(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"source.db"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE opaque_state(id INTEGER PRIMARY KEY, payload TEXT)")
                db.execute("INSERT INTO opaque_state VALUES(1,'private-marker')")
                db.execute("CREATE TABLE identity_queue(id INTEGER)")
            out=io.StringIO()
            with redirect_stdout(out):
                main(["--snapshot",str(source),"--all-tables"])
            data=json.loads(out.getvalue())[str(source)]
            self.assertTrue(data["all_tables_included"])
            self.assertEqual([t["table"] for t in data["tables"]],
                             ["identity_queue","opaque_state"])
            self.assertFalse(data["tables"][1]["operational_candidate"])
            self.assertEqual(data["tables"][1]["rows"],1)
            self.assertNotIn("private-marker",out.getvalue())

    def test_default_still_filters_nonoperational_names(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/"source.db"
            with sqlite3.connect(source) as db:
                db.execute("CREATE TABLE opaque_state(id INTEGER)")
                db.execute("CREATE TABLE identity_queue(id INTEGER)")
            out=io.StringIO()
            with redirect_stdout(out):
                main(["--snapshot",str(source)])
            data=json.loads(out.getvalue())[str(source)]
            self.assertEqual([t["table"] for t in data["tables"]],["identity_queue"])
            self.assertFalse(data["all_tables_included"])

if __name__=="__main__":
    unittest.main()
