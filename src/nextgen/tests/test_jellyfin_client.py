"""Offline Jellyfin library-scan adapter behavior; unexecuted under project policy."""
from urllib.error import HTTPError, URLError
import unittest

from src.nextgen.jellyfin import (JellyfinClient,JellyfinOptions,
    JellyfinConfigurationInvalid,JellyfinUnavailable)


class FakeResponse:
    def __init__(self,status=204,data=b""):self.status=status;self.data=data
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self,n):return self.data[:n]


class JellyfinClientTests(unittest.TestCase):
    def config(self):
        return JellyfinOptions("https://jellyfin.internal","abcdef0123456789",timeout_seconds=5)

    def test_accepts_scan_request_without_publishing_media_or_credentials(self):
        calls=[]
        def opener(req,timeout):
            calls.append((req.get_method(),req.full_url,req.headers,timeout))
            return FakeResponse()
        options=self.config()
        JellyfinClient(options,opener=opener).request_scan()
        self.assertEqual(len(calls),1)
        method,url,headers,timeout=calls[0]
        self.assertEqual(method,"POST")
        self.assertEqual(url,"https://jellyfin.internal/Library/Refresh")
        self.assertEqual(timeout,5)
        self.assertIn("MediaBrowser Token=",headers["Authorization"])
        self.assertNotIn(options.api_key,url)
        self.assertNotIn(options.api_key,repr(options))

    def test_invalid_endpoint_key_timeout_fail_without_network(self):
        for kwargs in (
            {"base_url":"https://server.internal/base"},
            {"api_key":""},
            {"api_key":"wrong key"},
            {"timeout_seconds":61},
        ):
            with self.subTest(kwargs=kwargs),self.assertRaises(JellyfinConfigurationInvalid):
                JellyfinOptions(**{**{"base_url":"https://server.internal",
                            "api_key":"abcdef0123456789","timeout_seconds":15},**kwargs})

    def test_transport_errors_are_safe(self):
        for failure,exception in (
            (URLError("private endpoint token"),JellyfinUnavailable),
            (HTTPError("https://server/api?private=secret",500,"hidden",None,None),JellyfinUnavailable),
            (HTTPError("https://server/api?private=secret",401,"hidden",None,None),JellyfinConfigurationInvalid),
        ):
            with self.subTest(failure=failure):
                def opener(req,timeout):raise failure
                with self.assertRaises(exception) as raised:
                    JellyfinClient(self.config(),opener=opener).request_scan()
                self.assertNotIn("private",str(raised.exception))
                self.assertNotIn("secret",str(raised.exception))

    def test_nonaccepted_response_never_confirms_scan(self):
        for status in (301,404,500):
            with self.subTest(status=status):
                with self.assertRaises(JellyfinUnavailable):
                    JellyfinClient(self.config(),opener=lambda *_args,**_kw:FakeResponse(status)).request_scan()


if __name__=="__main__":unittest.main()
