"""No-network XML diagnostics and source attribution regressions."""
import io
import logging
import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from anime_anidb_episode_lookup import lookup_episode_id
from anime_xml_response_diagnostics import (
    InvalidXMLResponse,log_bad_xml,response_metadata
)
from anime_fresh_database import initialize
from anime_unified_identity_monitor import check_once
from anime_ntfy_monitor import check_once as alerts


class FakeResponse:
    def __init__(self,data,*,status=200,content_type="text/html"):
        self.data=data
        self.status=status
        self.headers={"Content-Type":content_type}
    def __enter__(self):
        return self
    def __exit__(self,*args):
        return None
    def read(self,size):
        return self.data[:size]


class XMLResponseDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder=Path(self.tmp.name)
        self.metadata=self.folder/"anime-metadata.db"

    def call_anidb(self,opener):
        return lookup_episode_id(456,2,client="private-client-name",
            clientver=1,metadata_path=self.metadata,now=10000,opener=opener)

    def test_html_instead_of_anime_xml_reports_exact_endpoint_and_safe_preview(self):
        payload=b'<html><body>api_key=TOPSECRET token=PRIVATETOKEN Service unavailable</body></html>'
        with self.assertLogs("anime_xml_response_diagnostics",level="WARNING") as lines:
            with self.assertRaises(InvalidXMLResponse) as err:
                self.call_anidb(lambda *_args,**_kwargs: FakeResponse(payload))
        self.assertEqual(err.exception.source,"ANIDB_EPISODE_HTTP")
        message=" ".join(lines.output)
        self.assertIn("endpoint=http://api.anidb.net:9001/httpapi",message)
        self.assertIn("http_status=200",message)
        self.assertIn("content_type=text/html",message)
        self.assertIn("reason=ValueError",message)
        self.assertIn("preview=",message)
        self.assertNotIn("TOPSECRET",message)
        self.assertNotIn("PRIVATETOKEN",message)
        self.assertNotIn("private-client-name",message)
        with sqlite3.connect(self.metadata) as db:
            self.assertEqual(db.execute("SELECT count(*) FROM anidb_anime_catalog").fetchone()[0],0)

    def test_malformed_xml_logs_http_status_type_and_fingerprint(self):
        with self.assertLogs("anime_xml_response_diagnostics",level="WARNING") as lines:
            with self.assertRaises(InvalidXMLResponse):
                self.call_anidb(lambda *_args,**_kwargs:
                    FakeResponse(b"<anime id='456'><episodes><episode",content_type="application/xml"))
        message=" ".join(lines.output)
        self.assertIn("reason=ParseError",message)
        self.assertIn("sha256_12=",message)
        self.assertIn("content_type=application/xml",message)

    def test_http_error_response_is_logged_and_retried_not_cached(self):
        def failed(_request,timeout):
            raise urllib.error.HTTPError("http://api.anidb.net:9001/httpapi",
                403,"Forbidden",{"Content-Type":"text/plain"},
                io.BytesIO(b'Upstream access denied'))
        with self.assertLogs("anime_xml_response_diagnostics",level="WARNING") as lines:
            with self.assertRaises(InvalidXMLResponse) as exc:
                self.call_anidb(failed)
        self.assertEqual(exc.exception.source,"ANIDB_EPISODE_HTTP")
        self.assertIn("http_status=403"," ".join(lines.output))
        self.assertIn("Upstream access denied"," ".join(lines.output))

    def test_error_source_controls_retry_and_ntfy_does_not_fire(self):
        db_path=self.folder/"operations.db"
        initialize(db_path)
        with sqlite3.connect(db_path,isolation_level=None) as db:
            db.execute("""INSERT INTO notifications
                (source,release_name,source_guid,info_hash,received_at,status)
                VALUES ('nyaa','Example - 02','test-metadata',?,1,'IDENTIFYING')""",("a"*40,))
            for now in (1000,1400,2000,3000):
                def probe(*_):
                    raise InvalidXMLResponse("ANIDB_EPISODE_HTTP","ParseError")
                check_once(db,{}, {},now=now,probe=probe)
                identity=db.execute("SELECT decision,evidence_json FROM unified_identity_checks").fetchone()
                self.assertEqual(identity[0],"LOOKUP_RETRY")
                self.assertIn("METADATA_UNAVAILABLE_ANIDB_EPISODE_HTTP",identity[1])
                self.assertEqual(alerts(db,{"ntfy":{"enabled":True,"reminder_hours":1}},
                                        {},now=now+1,sender=lambda *_:self.fail("NTFY early"))["sent"],0)

    def test_rejects_arbitrary_endpoint_labels_without_logging_secrets(self):
        with self.assertRaises(ValueError):
            response_metadata("ATTACK","key=secret".encode())
        item=response_metadata("ANIME_LISTS",b'<broken')
        self.assertEqual(item["bytes"],7)
        self.assertIn("raw.githubusercontent.com",item["endpoint"])


if __name__=="__main__":
    unittest.main()
