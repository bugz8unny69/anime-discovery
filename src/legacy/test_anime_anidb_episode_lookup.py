"""Offline AniDB HTTP episode catalog/cache tests: never contact AniDB."""
import gzip
import sqlite3
import tempfile
import zlib
import unittest
from pathlib import Path
from anime_anidb_episode_lookup import (
    API_URL, MAX_BYTES, AniDBLookupDeferred, decode_episode_xml,
    parse_catalog, parse_episode_id, lookup_episode_id,
)

XML=b'''<anime id="456"><episodes>
<episode id="9876"><epno type="1">02</epno></episode>
<episode id="9877"><epno type="1">3</epno></episode>
<episode id="9910"><epno type="2">2</epno></episode>
</episodes></anime>'''


class FakeResponse:
    def __init__(self, data, *, encoding=None):
        self.data=data
        self.status=200
        self.headers={"Content-Type":"text/xml"}
        if encoding is not None:
            self.headers["Content-Encoding"]=encoding
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
        self.encoding=None

    def opener(self,request,timeout):
        self.urls.append(request.full_url)
        self.assertEqual(timeout,30)
        self.assertTrue(request.full_url.startswith(API_URL+"?"))
        self.assertIn("client=registeredclient",request.full_url)
        self.assertNotIn("password",request.full_url.lower())
        self.assertIn("gzip",request.get_header("Accept-encoding"))
        return FakeResponse(self.payload,encoding=self.encoding)

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

    def test_episode_ids_are_scoped_to_the_anidb_anime_record(self):
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        # A second anime with episode 2 cannot borrow the first anime's EID.
        with self.assertRaises(AniDBLookupDeferred):
            self.resolve(789,2,now=100001)
        self.payload=(b'<anime id="789"><episodes><episode id="5555">'
                      b'<epno type="1">2</epno></episode></episodes></anime>')
        self.assertEqual(self.resolve(789,2,now=100010),5555)
        self.assertEqual(self.resolve(456,2,now=100011),9876)
        self.assertEqual(len(self.urls),2)

    def test_invalid_cached_episode_identity_fails_without_network(self):
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        with sqlite3.connect(self.db_path) as db:
            db.execute("PRAGMA foreign_keys=OFF")
            db.execute("DELETE FROM anidb_anime_catalog WHERE anidb_id=456")
        with self.assertRaisesRegex(ValueError,"Unverified AniDB episode cache"):
            self.resolve(456,2,now=100020)
        self.assertEqual(len(self.urls),1)

    def test_missing_episode_after_clock_rollback_does_not_suppress_refresh(self):
        self.assertIsNone(self.resolve(456,8,now=100000))
        self.payload=XML.replace(b'</episodes>',
            b'<episode id="9999"><epno type="1">8</epno></episode></episodes>')
        self.assertEqual(self.resolve(456,8,now=99990),9999)
        self.assertEqual(len(self.urls),2)

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

    def test_gzip_compressed_xml_with_content_encoding(self):
        self.payload=gzip.compress(XML)
        self.encoding="gzip"
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        self.assertEqual(self.resolve(456,3,now=100001),9877)
        self.assertEqual(len(self.urls),1)

    def test_gzip_compressed_without_content_encoding_header(self):
        self.payload=gzip.compress(XML)
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        self.assertEqual(len(self.urls),1)

    def test_deflate_zlib_encoding_and_magic_sniffing(self):
        self.payload=zlib.compress(XML)
        self.encoding="deflate"
        self.assertEqual(self.resolve(456,2,now=100000),9876)
        self.assertEqual(len(self.urls),1)
        content,coding=decode_episode_xml(zlib.compress(XML))
        self.assertEqual((content,coding),(XML,"deflate"))

    def test_uncompressed_legacy_xml_still_supported(self):
        self.assertEqual(decode_episode_xml(XML),(XML,"identity"))
        self.assertEqual(self.resolve(456,2,now=100000),9876)

    def test_compressed_error_is_logged_after_decompression_and_not_cached(self):
        from anime_xml_response_diagnostics import InvalidXMLResponse
        self.encoding="gzip"
        self.payload=gzip.compress(b'<error code="555">Temporary failure</error>')
        with self.assertLogs("anime_xml_response_diagnostics",level="WARNING") as captured:
            with self.assertRaises(InvalidXMLResponse) as exc:
                self.resolve(456,2,now=100000)
        self.assertEqual(exc.exception.kind,"ANIDB_ERROR_555")
        message=" ".join(captured.output)
        self.assertIn("content_encoding=gzip",message)
        self.assertIn("http_status=200",message)
        self.assertIn("preview=",message)
        self.assertIn("Temporary failure",message)
        self.assertIn("encoded_bytes=",message)
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM anidb_anime_catalog").fetchone()[0],0)

    def test_corrupt_or_oversized_compressed_response_fails_closed(self):
        from anime_xml_response_diagnostics import InvalidXMLResponse
        self.encoding="gzip"
        self.payload=gzip.compress(XML)[:-7]
        with self.assertRaises(InvalidXMLResponse):
            self.resolve(456,2,now=100000)
        with self.assertRaisesRegex(ValueError,"oversized"):
            decode_episode_xml(gzip.compress(b'A'*(MAX_BYTES+1)),
                               encoding="gzip")
        with self.assertRaises(ValueError):
            decode_episode_xml(XML,encoding="br")
        with sqlite3.connect(self.db_path) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM anidb_anime_catalog").fetchone()[0],0)

    def test_no_client_or_invalid_inputs(self):
        with self.assertRaises(ValueError):
            lookup_episode_id(456,2,client="",clientver=1,
                              metadata_path=self.db_path,opener=self.opener)
        with self.assertRaises(ValueError):
            self.resolve(456,0,now=100000)
        self.assertEqual(self.urls,[])


if __name__=="__main__":
    unittest.main()
