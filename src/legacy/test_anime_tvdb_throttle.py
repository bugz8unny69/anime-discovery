"""Offline shared TVDB pacing and backoff tests."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from anime_tvdb_throttle import (reserve_request,record_failure,record_success,
                                 TVDBDeferred,tvdb_scope,current_scope)

class TVDBThrottleTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/"tvdb.db"

    def test_reservation_is_shared_and_defers_without_network(self):
        reserve_request(self.path,now=100)
        with self.assertRaises(TVDBDeferred) as cm:
            reserve_request(self.path,now=100)
        self.assertEqual(cm.exception.retry_after_seconds,1)
        reserve_request(self.path,now=101)

    def test_429_retry_after_and_success_reset(self):
        reserve_request(self.path,now=100)
        record_failure(self.path,429,"120",now=100)
        with self.assertRaises(TVDBDeferred) as cm:
            reserve_request(self.path,now=150)
        self.assertEqual(cm.exception.retry_after_seconds,70)
        reserve_request(self.path,now=220)
        record_success(self.path)
        record_failure(self.path,503,None,now=222)
        with self.assertRaises(TVDBDeferred) as cm:
            reserve_request(self.path,now=222)
        self.assertEqual(cm.exception.retry_after_seconds,10)

    def test_scope_restores_and_cannot_affect_unscoped_call(self):
        self.assertIsNone(current_scope())
        with tvdb_scope(self.path):
            self.assertEqual(current_scope(),self.path)
        self.assertIsNone(current_scope())

    def test_scoped_tvdb_token_and_metadata_cache_without_bypassing_verification(self):
        import json
        from unittest.mock import patch
        from anime_identity_verify import tvdb_token,request_json,TVDB_URL
        from anime_tvdb_response_cache import _entries
        _entries.clear()
        urls=[]
        class Reply:
            def __init__(self,data):
                self.data=data
            def __enter__(self):
                return self
            def __exit__(self,*args):
                pass
        def urlopen(req,timeout):
            urls.append(req.full_url)
            if req.full_url.endswith("/login"):
                return Reply('{"data":{"token":"secret-token"}}')
            if req.full_url.endswith("/extended"):
                return Reply('{"data":{"id":123,"name":"Example"}}')
            return Reply('{"data":{"episodes":[{"id":77,"seasonNumber":2,"number":3}]}}')
        with patch("anime_identity_verify.urllib.request.urlopen",side_effect=urlopen):
            with tvdb_scope(self.path):
                token=tvdb_token("key")
                self.assertEqual(tvdb_token("key"),token)
                # Worker's request spacing is still used on an actual miss.
                with patch("anime_identity_verify.reserve_request"):
                    first=request_json(TVDB_URL+"/series/123/extended",bearer=token)
                    first["data"]["name"]="tampered"
                    second=request_json(TVDB_URL+"/series/123/extended",bearer=token)
                    self.assertEqual(second["data"]["name"],"Example")
                    request_json(TVDB_URL+"/series/123/episodes/default?page=0",bearer=token)
                    request_json(TVDB_URL+"/series/123/episodes/default?page=0",bearer=token)
                self.assertEqual(len(urls),3)
        _entries.clear()

    def test_tvdb_cache_ttl_and_bearer_scoping(self):
        from anime_tvdb_response_cache import cache_get,cache_put,_entries
        _entries.clear()
        cache_put(self.path,"episodes",("bearer-a","url"),{"data":[1]},now=100)
        self.assertEqual(cache_get(self.path,"episodes",("bearer-a","url"),now=399),{"data":[1]})
        self.assertIsNone(cache_get(self.path,"episodes",("bearer-a","url"),now=400))
        self.assertIsNone(cache_get(self.path,"episodes",("bearer-b","url"),now=101))
        _entries.clear()

    def test_failed_tvdb_request_is_not_cached(self):
        from unittest.mock import patch
        from anime_identity_verify import request_json,TVDB_URL
        from anime_tvdb_response_cache import _entries
        _entries.clear()
        with tvdb_scope(self.path):
            with patch("anime_identity_verify.reserve_request"):
                with patch("anime_identity_verify.urllib.request.urlopen",side_effect=TimeoutError):
                    with self.assertRaises(TVDBDeferred):
                        request_json(TVDB_URL+"/series/123/extended",bearer="token")
                self.assertFalse(any(item[1]=="series" for item in _entries))
        _entries.clear()

if __name__=="__main__":
    unittest.main()
