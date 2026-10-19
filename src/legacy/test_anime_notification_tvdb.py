"""Unit coverage for TVDB verification and NTFY delivery."""
import json
import unittest
from anime_ntfy import notify_review
from anime_tvdb import lookup_tvdb

class Response:
    status=200
    def __init__(self,payload=None): self.payload=payload
    def __enter__(self):return self
    def __exit__(self,*args): pass
    def read(self):return json.dumps(self.payload).encode()

class IntegrationTests(unittest.TestCase):
    def test_ntfy_uses_private_token_header(self):
        requests=[]
        def opener(req,timeout):
            requests.append(req)
            return Response()
        cfg={"ntfy":{"enabled":True,"server":"https://notify.example",
                       "topic":"anime-review","dashboard_url":"https://anime.example","reminder_hours":24}}
        self.assertTrue(notify_review(cfg,{"ntfy_token":"test"},12,"Test anime",opener=opener))
        self.assertEqual(requests[0].get_header("Authorization"),"Bearer test")
        self.assertEqual(requests[0].get_header("Click"),"https://anime.example/jobs")
    def test_ntfy_disabled(self):
        self.assertFalse(notify_review({"ntfy":{"enabled":False}}, {},1,"Test"))
    def test_tvdb_lookup_checks_exact_id(self):
        requests=[]
        def opener(req,timeout):
            requests.append(req)
            return Response({"data":{"token":"temporary-token"}} if len(requests)==1 else {"data":{"id":123,"name":"Example"}})
        cfg={"tvdb":{"enabled":True,"base_url":"https://api4.thetvdb.com/v4"}}
        result=lookup_tvdb(cfg,{"tvdb_api_key":"test-key"},123,opener=opener)
        self.assertEqual(result,{"tvdb_id":123,"name":"Example"})
        self.assertEqual(requests[1].get_header("Authorization"),"Bearer temporary-token")
    def test_tvdb_identity_mismatch(self):
        def opener(req,timeout):
            return Response({"data":{"token":"token"}} if req.get_method()=="POST" else {"data":{"id":999}})
        with self.assertRaises(RuntimeError):
            lookup_tvdb({"tvdb":{"enabled":True,"base_url":"https://api4.thetvdb.com/v4"}},
                        {"tvdb_api_key":"key"},123,opener=opener)

if __name__=="__main__": unittest.main()
