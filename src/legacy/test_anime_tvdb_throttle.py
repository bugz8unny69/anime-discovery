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

if __name__=="__main__":
    unittest.main()
