import asyncio
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_safe_handlers import migration_preflight_handler,SAFE_HANDLERS

class SafeHandlersTests(unittest.TestCase):
    def test_invalid_payload_fails_closed(self):
        for payload in ("not json","[]",'{"wrong": 1}','{"database_path": ""}'):
            result=asyncio.run(migration_preflight_handler({"payload_json":payload}))
            self.assertEqual(result,"NEEDS_REVIEW")
        self.assertIn("migration_preflight",SAFE_HANDLERS)

    def test_bootstrap_is_not_approved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/"db.sqlite"
            with sqlite3.connect(path) as db:
                db.execute("CREATE TABLE schema_bootstrap(id INTEGER PRIMARY KEY,status TEXT)")
                db.execute("INSERT INTO schema_bootstrap VALUES(1,'PENDING_MIGRATIONS')")
            result=asyncio.run(migration_preflight_handler(
                {"payload_json":json.dumps({"database_path":str(path)})}))
            self.assertEqual(result,"NEEDS_REVIEW")

if __name__=="__main__":
    unittest.main()
