import json
import unittest
from anime_integration_connection import test_connection

class Response:
    status=200
    def __init__(self,obj): self.obj=obj
    def __enter__(self): return self
    def __exit__(self,*unused): return False
    def read(self,*unused): return json.dumps(self.obj).encode()

class IntegrationProbeTests(unittest.TestCase):
    def test_sonarr_success_and_no_secret_in_response(self):
        cfg={"sonarr":{"enabled":True,"base_url":"https://sonarr.internal"}}
        sec={"sonarr_api_key":"do-not-leak"}
        def opener(req,timeout):
            self.assertEqual(req.get_header("X-api-key"),"do-not-leak")
            self.assertEqual(timeout,8)
            return Response({"version":"4.0"})
        result=test_connection(cfg,sec,"sonarr",opener=opener)
        self.assertTrue(result["connected"])
        self.assertNotIn("do-not-leak",json.dumps(result))

    def test_tvdb_unsaved_api_key_login(self):
        cfg={"tvdb":{"enabled":True,"base_url":"https://api4.thetvdb.com/v4"}}
        def opener(req,timeout):
            self.assertEqual(req.full_url,"https://api4.thetvdb.com/v4/login")
            self.assertEqual(req.get_method(),"POST")
            self.assertEqual(json.loads(req.data),{"apikey":"draft-secret"})
            return Response({"data":{"token":"session-token"}})
        result=test_connection(cfg,{"tvdb_api_key":"draft-secret"},"tvdb",opener=opener)
        self.assertTrue(result["connected"])
        self.assertNotIn("session-token",json.dumps(result))
        self.assertNotIn("draft-secret",json.dumps(result))

    def test_ntfy_post_is_explicit(self):
        cfg={"ntfy":{"enabled":True,"server":"https://ntfy.internal","topic":"test"}}
        sec={"ntfy_token":"hidden"}
        def opener(req,timeout):
            self.assertEqual(req.get_method(),"POST")
            self.assertIn("/test",req.full_url)
            return Response({})
        self.assertTrue(test_connection(cfg,sec,"ntfy",opener=opener)["connected"])

    def test_autobrr_does_not_send_mock_event(self):
        self.assertFalse(test_connection({},{},"autobrr",opener=lambda *_:self.fail("network"))["tested"])

    def test_disabled_is_not_fake_success(self):
        result=test_connection({"shoko":{"enabled":False}},{},"shoko",
                               opener=lambda *_:self.fail("network"))
        self.assertFalse(result["tested"])

if __name__=="__main__": unittest.main()
