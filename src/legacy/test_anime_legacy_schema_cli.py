import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from anime_legacy_schema_cli import main

class SchemaCliTests(unittest.TestCase):
    def test_exports_structure_not_row_values(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/"snapshot.db"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE download_history(id INTEGER, secret TEXT)")
                db.execute("INSERT INTO download_history VALUES(1,'sensitive-release-name')")
            out=io.StringIO()
            with redirect_stdout(out):
                main(["--snapshot",str(path)])
            text=out.getvalue()
            self.assertNotIn("sensitive-release-name",text)
            data=json.loads(text)
            self.assertEqual(data[str(path)]["tables"][0]["rows"],1)
            self.assertFalse(data[str(path)]["mapping_verified"])

if __name__=="__main__":
    unittest.main()
