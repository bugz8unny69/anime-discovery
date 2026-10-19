"""Offline HTTP tests for the actual browser and Autobrr routes."""
import base64
import http.client
import importlib.util
import json
import sqlite3
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path

from anime_fresh_database import initialize

MODULE=Path(__file__).with_name("anime-discovery-web.py")
spec=importlib.util.spec_from_file_location("anime_web_server_http_test",MODULE)
web=importlib.util.module_from_spec(spec)
spec.loader.exec_module(web)
HASH="a"*40


class DashboardHTTPTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.db=Path(tmp.name)/"web.db"
        initialize(self.db)
        self.server=ThreadingHTTPServer(("127.0.0.1",0),web.app(self.db,"secret-token"))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.thread.join,2)
        self.port=self.server.server_port

    def request(self,method,path,body=None,*,basic=False):
        headers={"Authorization":"Basic "+base64.b64encode(b"anime:secret-token").decode()
                 if basic else "Bearer secret-token"}
        if isinstance(body,dict):
            body=json.dumps(body)
            headers["Content-Type"]="application/json"
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            client.request(method,path,body,headers)
            response=client.getresponse()
            return response.status,response.getheader("Location"),response.read().decode()
        finally:
            client.close()

    def test_dashboard_login_and_status(self):
        status,_,content=self.request("GET","/",basic=True)
        self.assertEqual(status,200)
        self.assertIn("Anime Discovery",content)
        self.assertIn("Recognized anime names",content)
        self.assertEqual(self.request("GET","/health")[0],200)

    def test_http_webhook_approval_inspect_reject_and_reset(self):
        payload={"release_name":"Example S01E02","source_guid":"g-1","info_hash":HASH,
                 "tvdb_id":123,"anidb_id":456,"season":1,"episode":2}
        status,_,body=self.request("POST","/webhook",payload)
        self.assertEqual(status,200)
        result=json.loads(body)
        self.assertTrue(result["queued"])
        series_id=result["series_id"]
        status,_,content=self.request("GET","/series?id="+str(series_id))
        self.assertEqual(status,200)
        self.assertIn("Example S01E02",content)
        status,_,body=self.request("POST","/series-action",
             {"series_id":series_id,"action":"reject"})
        self.assertEqual(status,200)
        status,_,body=self.request("POST","/webhook",{**payload,"source_guid":"g-2","episode":3})
        self.assertEqual(status,400)
        self.assertIn("rejected",body)
        self.assertEqual(self.request("POST","/series-action",
             {"series_id":series_id,"action":"clear-history"})[0],200)
        self.assertEqual(self.request("POST","/series-action",
             {"series_id":series_id,"action":"reset"})[0],200)
        status,_,body=self.request("POST","/webhook",{**payload,"source_guid":"g-3","episode":3})
        self.assertEqual(status,200)
        self.assertTrue(json.loads(body)["queued"])


if __name__=="__main__":
    unittest.main()
