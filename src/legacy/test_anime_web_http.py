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
        self.assertIn("Anime-Trial library",content)
        self.assertIn("Rows per page",content)
        self.assertEqual(self.request("GET","/jobs")[0],200)
        self.assertEqual(self.request("GET","/recognized")[0],200)
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

    def test_unstaged_series_are_jobs_not_library(self):
        event={"release_name":"Example S01E02","source_guid":"unstaged-1",
               "info_hash":HASH,"tvdb_id":123,"anidb_id":456,
               "season":1,"episode":2}
        status,_,body=self.request("POST","/webhook",event)
        self.assertEqual(status,200)
        status,_,library=self.request("GET","/")
        self.assertIn("No series have reached Anime-Trial",library)
        self.assertNotIn("Example S01E02</a>",library)
        status,_,jobs=self.request("GET","/api/jobs")
        self.assertEqual(status,200)
        entry=json.loads(jobs)["items"][0]
        self.assertEqual(entry["status"],"QUEUED")
        self.assertEqual(entry["source"],"autobrr")
        self.assertEqual(entry["episode"],2)

    def test_staged_series_paginate_and_bulk_manage(self):
        with sqlite3.connect(self.db,isolation_level=None) as db:
            db.execute("PRAGMA foreign_keys=ON")
            for index in range(1,56):
                sid=db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb',?,?)",
                    (str(10000+index),"Title %03d"%index)).lastrowid
                nid=db.execute("""INSERT INTO notifications
                    (source,release_name,source_guid,info_hash,received_at)
                    VALUES ('autobrr',?,?,?,?)""",
                    ("Title %03d"%index,"guid-"+str(index),HASH,index)).lastrowid
                db.execute("""INSERT INTO episode_dispatch
                    (notification_id,series_id,season,episode,state)
                    VALUES (?,?,1,1,'DONE')""",(nid,sid))
                stage=Path(self.db).parent/("stage-"+str(index)+".mkv")
                stage.write_bytes(b"media")
                db.execute("""INSERT INTO torrent_recovery_records
                    (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
                    VALUES (?,?,?,?,?,0)""",
                    (nid,HASH,"magnet:?xt=urn:btih:"+HASH,str(stage),"sha"))
        status,_,first=self.request("GET","/?page=1&size=20")
        self.assertEqual(status,200)
        self.assertIn("55 total",first)
        self.assertIn("Page 1 of 3",first)
        self.assertEqual(first.count('class="pick"'),20)
        status,_,second=self.request("GET","/?page=2&size=50")
        self.assertEqual(status,200)
        self.assertIn("Page 2 of 2",second)
        self.assertEqual(second.count('class="pick"'),5)
        selected={"series_ids":[1,2],"action":"reject"}
        status,_,body=self.request("POST","/series-bulk",selected)
        self.assertEqual(status,200)
        self.assertEqual(json.loads(body)["updated"],2)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("""SELECT count(*) FROM series_rejection_blocks
                WHERE series_id IN (1,2)""").fetchone()[0],2)
        status,_,body=self.request("POST","/series-bulk",
            {"series_ids":[1,999999],"action":"reset"})
        self.assertEqual(status,400)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("""SELECT count(*) FROM series_rejection_blocks
                WHERE series_id IN (1,2)""").fetchone()[0],2)


if __name__=="__main__":
    unittest.main()
