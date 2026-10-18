import io, json, sqlite3, tempfile, unittest
from pathlib import Path
from historical_search import process, search

class Response(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self,*args): self.close()

class SearchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.db=str(Path(self.tmp.name)/'jobs.db')
        with sqlite3.connect(self.db) as db:
            db.execute('CREATE TABLE episode_jobs(tvdb_id INTEGER, season INTEGER, episode INTEGER, state TEXT)')
            db.executemany('INSERT INTO episode_jobs VALUES(?,?,?,?)',[(389597,1,1,'SEARCH_REQUIRED'),(389597,1,2,'BLOCKED_VERIFICATION')])
        self.catalog=Path(self.tmp.name)/'catalog.json'; self.catalog.write_text('{"389597":"Solo Leveling"}')
        self.catalog_path=str(self.catalog)
        self.calls=[]
    def opener(self,req,timeout):
        self.calls.append(req)
        return Response(json.dumps([{'title':'Solo Leveling S01E01','guid':'guid1','downloadUrl':'https://example.test/a'}]).encode())
    def test_search_and_idempotent(self):
        a=process(self.db,'http://localhost:9696','key',catalog_path=self.catalog_path,opener=self.opener)
        self.assertEqual(a[0]['status'],'SEARCHED')
        self.assertIn('S01E01',self.calls[0].full_url)
        self.assertEqual(self.calls[0].get_header('X-api-key'),'key')
        self.assertEqual(process(self.db,'http://localhost:9696','key',catalog_path=self.catalog_path,opener=self.opener)[0]['status'],'ALREADY_SEARCHED')
        self.assertEqual(len(self.calls),1)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT trust_state FROM historical_candidates').fetchone()[0],'UNTRUSTED')
            self.assertEqual(db.execute('SELECT count(*) FROM historical_candidates').fetchone()[0],1)
    def test_blocked_episode_not_searched(self):
        process(self.db,'http://localhost:9696','key',catalog_path=self.catalog_path,opener=self.opener)
        self.assertEqual(len(self.calls),1)
    def test_missing_catalog_fails_closed(self):
        self.catalog.write_text('{}')
        self.assertEqual(process(self.db,'http://localhost:9696','key',catalog_path=self.catalog_path,opener=self.opener)[0]['status'],'MISSING_TRUSTED_SERIES_TITLE')
        self.assertFalse(self.calls)
    def test_bad_api_response_no_marker(self):
        def bad(req,timeout): return Response(b'{"error":"invalid"}')
        self.assertEqual(process(self.db,'http://localhost:9696','key',catalog_path=self.catalog_path,opener=bad)[0]['status'],'SEARCH_ERROR')
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute('SELECT count(*) FROM historical_search_attempts').fetchone()[0],0)
    def test_no_api_key(self):
        with self.assertRaises(ValueError): process(self.db,'http://localhost:9696','',catalog_path=self.catalog_path,opener=self.opener)
    def test_url_validation(self):
        with self.assertRaises(ValueError): search('file:///tmp','key','a',opener=self.opener)
if __name__=='__main__': unittest.main()
