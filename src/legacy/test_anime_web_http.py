"""Offline HTTP tests for the actual browser and Autobrr routes."""
import base64
import hashlib
import urllib.parse
from unittest.mock import patch
import anime_dashboard_auth
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
        self.auth_patch=patch.object(anime_dashboard_auth,"AUTH_FILE",Path(tmp.name)/"dashboard-auth.json")
        self.auth_patch.start()
        self.addCleanup(self.auth_patch.stop)
        anime_dashboard_auth.set_password("admin-pass-long")
        self.session=anime_dashboard_auth.session_token()
        self.csrf=hashlib.sha256(self.session.encode()).hexdigest()
        self.server=ThreadingHTTPServer(("127.0.0.1",0),web.app(self.db,"secret-token",admin_password="admin-pass"))
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True)
        self.thread.start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.addCleanup(self.thread.join,2)
        self.port=self.server.server_port

    def request(self,method,path,body=None,*,basic=False):
        headers=({"Authorization":"Bearer secret-token"} if path=="/webhook" and not basic
            else {"Cookie":"ad_session="+self.session,"X-CSRF-Token":self.csrf})
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

    def test_webhook_token_cannot_access_dashboard(self):
        import http.client
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            client.request("GET","/",headers={"Authorization":"Bearer secret-token"})
            response=client.getresponse()
            self.assertEqual(response.status,303)
            self.assertEqual(response.getheader("Location"),"/login")
            response.read()
            client.request("POST","/webhook","{}",headers={
                "Authorization":"Basic "+base64.b64encode(b"anime:admin-pass").decode(),
                "Content-Type":"application/json"})
            response=client.getresponse()
            self.assertEqual(response.status,401)
            response.read()
        finally:
            client.close()

    def test_login_cookie_invalid_credentials_and_logout(self):
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            client.request("GET","/login")
            r=client.getresponse()
            self.assertEqual(r.status,200)
            page=r.read().decode()
            self.assertIn('<form method="post" action="/login">',page)
            self.assertNotIn('WWW-Authenticate',str(r.getheaders()))
            for password,expected in (("wrong",401),("admin-pass-long",303)):
                values=urllib.parse.urlencode({"username":"admin","password":password})
                client.request("POST","/login",values,{"Content-Type":"application/x-www-form-urlencoded"})
                r=client.getresponse()
                self.assertEqual(r.status,expected)
                cookie=r.getheader("Set-Cookie")
                r.read()
            self.assertIn("HttpOnly",cookie)
            self.assertIn("SameSite=Lax",cookie)
            token=cookie.split(";",1)[0].split("=",1)[1]
            csrf=hashlib.sha256(token.encode()).hexdigest()
            client.request("POST","/logout","x=1",{"Cookie":"ad_session="+token,
                           "X-CSRF-Token":csrf,"Content-Type":"application/x-www-form-urlencoded"})
            r=client.getresponse()
            self.assertEqual(r.status,303)
            r.read()
            client.request("GET","/",headers={"Cookie":"ad_session="+token})
            r=client.getresponse()
            self.assertEqual(r.status,303)
            r.read()
        finally:
            client.close()

    def test_settings_page_provides_working_csrf_for_integration_actions(self):
        import os
        import re
        from anime_flat_config import DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (folder/"secrets.json").write_text(json.dumps({"web_token":"hidden-token"}))
            os.chmod(folder/"secrets.json",0o600)
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"secret-token",config_dir=folder))
            worker=threading.Thread(target=server.serve_forever,daemon=True)
            worker.start()
            client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            try:
                client.request("GET","/settings",headers={"Cookie":"ad_session="+self.session})
                response=client.getresponse()
                self.assertEqual(response.status,200)
                page=response.read().decode()
                fields=re.findall(r'<input type="hidden" name="_csrf" value="([^"]+)">',page)
                self.assertGreaterEqual(len(fields),5)
                self.assertTrue(all(item==self.csrf for item in fields))
                client.request("POST","/api/test-connection",
                    json.dumps({"service":"autobrr"}),
                    {"Cookie":"ad_session="+self.session,"Content-Type":"application/json",
                     "X-CSRF-Token":fields[0]})
                result=client.getresponse()
                self.assertEqual(result.status,200)
                self.assertFalse(json.loads(result.read())["tested"])
                client.request("POST","/api/credentials",
                    json.dumps({"key":"ntfy_token","clear":False,"value":"replacement"}),
                    {"Cookie":"ad_session="+self.session,"Content-Type":"application/json",
                     "X-CSRF-Token":fields[0]})
                result=client.getresponse()
                self.assertEqual(result.status,200)
                result.read()
                self.assertEqual(json.loads((folder/"secrets.json").read_text())["ntfy_token"],
                                 "replacement")
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                worker.join(2)

    def test_credential_reveal_requires_admin_password_and_never_caches(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (folder/"secrets.json").write_text(json.dumps({
                "web_token":"hidden-webhook","sonarr_api_key":"sample-secret"}))
            os.chmod(folder/"secrets.json",0o600)
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"secret-token",config_dir=folder))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            try:
                headers={"Cookie":"ad_session="+self.session,
                         "X-CSRF-Token":self.csrf,
                         "Content-Type":"application/json"}
                for password,expected in (("wrong",403),("admin-pass-long",200)):
                    client.request("POST","/api/credential-reveal",
                        json.dumps({"key":"sonarr_api_key","password":password}),headers)
                    response=client.getresponse()
                    self.assertEqual(response.status,expected)
                    self.assertEqual(response.getheader("Cache-Control"),"no-store" if expected==200 else None)
                    body=json.loads(response.read())
                    if expected==200:
                        self.assertEqual(body["value"],"sample-secret")
                    else:
                        self.assertNotIn("sample-secret",json.dumps(body))
                client.request("POST","/api/credential-reveal",
                    json.dumps({"key":"sonarr_api_key","password":"admin-pass-long"}),
                    {"Cookie":"ad_session="+self.session,"Content-Type":"application/json"})
                response=client.getresponse()
                self.assertEqual(response.status,403)
                response.read()
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_session_mutations_require_csrf(self):
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            client.request("POST","/series-bulk",json.dumps({"series_ids":[1],"action":"reset"}),
                           {"Cookie":"ad_session="+self.session,
                            "Content-Type":"application/json"})
            r=client.getresponse()
            self.assertEqual(r.status,403)
            r.read()
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

    def test_request_anime_without_prowlarr_stays_disabled(self):
        status,_,body=self.request("POST","/request-anime",
            {"title":"Example Show","season":1})
        self.assertEqual(status,400)
        self.assertIn("Configure Prowlarr",body)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM daemon_jobs WHERE kind='series_gap_search'").fetchone()[0],0)

    def test_manual_request_with_recognized_identity_creates_search_only(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)
            config=json.loads(json.dumps(DEFAULT_SETTINGS))
            config["prowlarr"]={"enabled":True,"base_url":"http://127.0.0.1:9696"}
            config["identity"]["series_map"]={"Example Show":{
                "tvdb_id":123,"anidb_id":456,"season":1}}
            (directory/"settings.json").write_text(json.dumps(config))
            (directory/"secrets.json").write_text(json.dumps({"prowlarr_api_key":"test"}))
            os.chmod(directory/"secrets.json",0o600)
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"secret-token",config_dir=directory,admin_password="admin-pass"))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                client.request("POST","/request-anime",
                    json.dumps({"tvdb_id":123,"season":1}),
                    {"Cookie":"ad_session="+self.session,"X-CSRF-Token":self.csrf,"Content-Type":"application/json"})
                result=client.getresponse()
                self.assertEqual(result.status,200)
                self.assertEqual(json.loads(result.read())["source"],"manual")
                client.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT count(*) FROM daemon_jobs WHERE kind='series_gap_search'").fetchone()[0],1)
            self.assertEqual(db.execute("SELECT count(*) FROM episode_dispatch").fetchone()[0],0)


if __name__=="__main__":
    unittest.main()
