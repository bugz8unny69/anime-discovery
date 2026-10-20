"""Offline AniDB HTTP episode catalog/cache tests: never contact AniDB."""
import sqlite3
import tempfile
import unittest
from pathlib import Path
from anime_anidb_episode_lookup import (
    API_URL, AniDBLookupDeferred, parse_catalog, parse_episode_id,
    lookup_episode_id,
)

XML=b'''<anime id="456"><episodes>
<episode id="9876"><epno type="1">02</epno></episode>
<episode id="9877"><epno type="1">3</epno></episode>
<episode id="9910"><epno type="2">2</epno></episode>
</episodes></anime>'''


class FakeResponse:
    def __init__(self, data):
        self.data=data
    def __enter__(self):
        return self
    def __exit__(self,*args):
        pass
    def read(self,size):
        return self.data[:size]


class AniDBEpisodeLookupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path=Path(self.tmp.name)/"anime-metadata.db"
        self.urls=[]
        self.payload=XML

    def opener(self,request,timeout):
        self.urls.append(request.full_url)
        self.assertEqual(timeout,30)
        self.assertTrue(request.full_url.startswith(API_URL+"?"))
        self.assertIn("client=registeredclient",request.full_url)
        self.assertNotIn("password",request.full_url.lower())
        return FakeResponse(self.payload)

    def resolve(self,aid,number,*,now):
        return lookup_episode_id(aid,number,client="registeredclient",
            clientver=1,metadata_path=self.db_path,now=now,opener=self.opener)

    def test_exact_regular_episode_only(self):
        self.assertEqual(parse_episode_id(XML,456,2),9876)
        self.assertEqual(parse_episode_id(XML,456,3),9877)
        self.assertIsNone(parse_episode_id(XML,456,4))
        with self.assertRaises(ValueError):
            parse_episode_id(XML,999,2)

    def test_duplicate_malformed_and_api_error_fail_closed(self):
        duplicate=XML.replace(b'</episodes>',
            b'<episode id="1111"><epno type="1">2</epno></episode></episodes>')
        for invalid in (duplicate,b'<error>Busy</error>',
                        b'<anime id="999"><episodes/></anime>',
                        b'<anime id="456"></anime>'):
            with self.assertRaises(ValueError):
                parse_catalog(invalid,456)

    def test_one_call_populates_multiple_episodes_and_separate_database(self):
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        self.assertEqual(self.resolve(456,3,now=100001),9877)
        self.assertEqual(self.resolve(456,8,now=100002),None)
        self.assertEqual(len(self.urls),1)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM anidb_episode_catalog").fetchone()[0],2)
            self.assertEqual(db.execute("SELECT regular_episode_count FROM anidb_anime_catalog").fetchone()[0],2)
        self.assertFalse((Path(self.tmp.name)/"anime-456.xml").exists())

    def test_unknown_episodes_refresh_at_most_daily(self):
        self.assertIsNone(self.resolve(456,9,now=100000))
        self.assertIsNone(self.resolve(456,9,now=100002))
        self.assertEqual(len(self.urls),1)
        newer=XML.replace(b'</episodes>',
            b'<episode id="9999"><epno type="1">9</epno></episode></episodes>')
        self.payload=newer
        self.assertEqual(self.resolve(456,9,now=186400),9999)
        self.assertEqual(len(self.urls),2)

    def test_shared_request_cooldown_does_not_count_as_bad_metadata(self):
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        with self.assertRaises(AniDBLookupDeferred) as err:
            self.resolve(789,1,now=100001)
        self.assertEqual(err.exception.retry_after_seconds,9)
        self.assertEqual(len(self.urls),1)
        self.payload=b'<anime id="789"><episodes><episode id="42"><epno type="1">1</epno></episode></episodes></anime>'
        self.assertEqual(self.resolve(789,1,now=100010),42)

    def test_rejected_response_never_poison_caches(self):
        self.payload=b'<error>Rate limit</error>'
        with self.assertRaises(ValueError):
            self.resolve(456,2,now=100000)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM anidb_anime_catalog").fetchone()[0],0)
        with self.assertRaises(AniDBLookupDeferred):
            self.resolve(456,2,now=100500)
        self.payload=XML
        self.assertEqual(self.resolve(456,2,now=100600),9876)

    def test_no_client_or_invalid_inputs(self):
        with self.assertRaises(ValueError):
            lookup_episode_id(456,2,client="",clientver=1,
                              metadata_path=self.db_path,opener=self.opener)
        with self.assertRaises(ValueError):
            self.resolve(456,0,now=100000)
        self.assertEqual(self.urls,[])


if __name__=="__main__":
    unittest.main()
