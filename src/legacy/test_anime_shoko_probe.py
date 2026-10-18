import json
import unittest
from anime_shoko_probe import inspect_shoko

class Response:
    status=200
    def __enter__(self):return self
    def __exit__(self,*args):return False
    def read(self):return b'{"Version":"test"}'

class Opener:
    def __init__(self):self.requests=[]
    def open(self,request,timeout=None):
        self.requests.append(request)
        return Response()

class ShokoProbeTests(unittest.TestCase):
    def test_read_only_probe_does_not_enable_writes(self):
        opener=Opener()
        result=inspect_shoko("http://localhost:8111",opener=opener)
        self.assertTrue(result["reachable"])
        self.assertFalse(result["writes_enabled"])
        self.assertFalse(result["episode_link_writes_validated"])
        self.assertEqual(opener.requests[0].full_url,
                         "http://localhost:8111/api/v3/Init/Status")
        self.assertIsNone(opener.requests[0].data)

if __name__=="__main__":
    unittest.main()
