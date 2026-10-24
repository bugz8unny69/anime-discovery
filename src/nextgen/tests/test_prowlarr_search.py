"""Offline Prowlarr candidate filter and header-only authentication; unrun."""
import io
import json
import unittest
from urllib.error import HTTPError

from src.nextgen.missing_search import (ProwlarrClient,SearchOptions,
    SearchConfigurationInvalid,SearchUnavailable,candidates)


class FakeReply:
    status=200
    def __init__(self,payload):self.data=io.BytesIO(json.dumps(payload).encode())
    def __enter__(self):return self
    def __exit__(self,*args):pass
    def read(self,size):return self.data.read(size)


class SearchTransportTests(unittest.TestCase):
    def options(self):return SearchOptions("https://prowlarr.internal","private-prowlarr-token")
    def test_one_canonical_episode_with_infohash(self):
        h="a"*40
        payload=[{"title":"Example Anime S01E02 1080p","infoHash":h},
                 {"title":"Different Anime S01E02 1080p","infoHash":"b"*40},
                 {"title":"Example Anime S01E03 1080p","infoHash":"c"*40},
                 {"title":"Example Anime - 02 1080p","infoHash":"d"*40},
                 {"title":"Example Anime S01E02 Batch","infoHash":"e"*40}]
        self.assertEqual(candidates(payload,series_title="Example Anime",season=1,episode=2),
                         ((h,"Example Anime S01E02 1080p"),))

    def test_search_is_read_only_and_credentials_never_in_url(self):
        calls=[]
        def opener(req,timeout):
            calls.append((req.get_method(),req.full_url,req.headers,timeout))
            return FakeReply([{"title":"Example Anime S01E01 1080p","infoHash":"a"*40}])
        results=ProwlarrClient(self.options(),opener=opener).search("Example Anime",1,1)
        self.assertEqual(len(results),1)
        method,url,headers,timeout=calls[0]
        self.assertEqual(method,"GET")
        self.assertIn("/api/v1/search?",url)
        self.assertIn("indexerIds=-2",url)
        self.assertEqual(headers["X-api-key"],"private-prowlarr-token")
        self.assertNotIn("private-prowlarr-token",url)

    def test_rejected_url_and_http_status_do_not_expose_secrets(self):
        with self.assertRaises(SearchConfigurationInvalid):
            SearchOptions("http://prowlarr.internal/base","private-prowlarr-token")
        def rejected(req,timeout):
            raise HTTPError(req.full_url,401,"AUTH-SECRET",{},None)
        with self.assertRaises(SearchConfigurationInvalid) as raised:
            ProwlarrClient(self.options(),opener=rejected).search("Example Anime",1,1)
        self.assertNotIn("SECRET",str(raised.exception))
        with self.assertRaises(SearchUnavailable):
            ProwlarrClient(self.options(),opener=lambda req,timeout:FakeReply({"error":"bad"})).search("Example Anime",1,1)


if __name__=="__main__":unittest.main()
