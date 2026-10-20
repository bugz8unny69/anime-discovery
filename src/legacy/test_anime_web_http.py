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

    def test_autobrr_json_body_authentication(self):
        payload={"source":"nyaa","release_name":"Example","source_guid":"g-body",
                 "info_hash":HASH,"token":"secret-token"}
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            for value,expected in (("secret-token",200),("wrong",401),("",401)):
                payload["token"]=value
                client.request("POST","/webhook",json.dumps(payload),
                    {"Content-Type":"application/json"})
                response=client.getresponse()
                self.assertEqual(response.status,expected)
                response.read()
        finally:
            client.close()

    def test_autobrr_url_token_with_json_body(self):
        import io
        from unittest.mock import patch
        payload={"release_name":"URL Auth Example","source_guid":"autobrr-url",
                 "info_hash":HASH}
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            client.request("POST","/webhook?token=secret-token",
                json.dumps(payload),{"Content-Type":"application/json"})
            response=client.getresponse()
            self.assertEqual(response.status,200)
            response.read()
            for url in ("/webhook","/webhook?token=wrong"):
                client.request("POST",url,json.dumps(payload),
                               {"Content-Type":"application/json"})
                response=client.getresponse()
                self.assertEqual(response.status,401)
                response.read()
        finally:
            client.close()

    def test_webhook_logging_redacts_query_token(self):
        import io
        handler=object.__new__(web.app(self.db,"secret-token"))
        handler.path="/webhook?token=sensitive-secret"
        handler.command="POST"
        handler.request_version="HTTP/1.1"
        captured=[]
        handler.log_message=lambda fmt,*args: captured.append(fmt%args)
        handler.log_request(401,"-")
        self.assertEqual(len(captured),1)
        self.assertIn("POST /webhook HTTP/1.1",captured[0])
        self.assertNotIn("sensitive-secret",captured[0])

    def test_unmatched_webhook_marks_review_and_does_not_queue(self):
        from anime_ntfy_monitor import check_once
        from anime_dashboard_queries import all_jobs
        values={"source":"nyaa","release_name":"Unverified release 02",
                "source_guid":"review-transition","info_hash":HASH,
                "token":"secret-token"}
        status,_,body=self.request("POST","/webhook",values)
        self.assertEqual(status,200)
        nid=json.loads(body)["notification_id"]
        with sqlite3.connect(self.db,isolation_level=None) as db:
            self.assertEqual(db.execute("SELECT status FROM notifications WHERE id=?",(nid,)).fetchone()[0],"IDENTIFYING")
            self.assertIsNone(db.execute("SELECT 1 FROM daemon_jobs WHERE subject_key=? AND kind='claimed_acquisition'",(str(nid),)).fetchone())
            self.assertEqual(all_jobs(db)["items"][0]["status"],"IDENTIFYING")
            sent=[]
            cfg={"ntfy":{"enabled":True,"reminder_hours":24}}
            sender=lambda settings,secrets,notification_id,title: sent.append(notification_id) or True
            self.assertEqual(check_once(db,cfg,{},now=1000,sender=sender)["sent"],0)
            self.assertEqual(sent,[])
            from anime_unified_identity_monitor import check_once as check_identity
            # The finalized check must not predate the webhook receipt.
            received=db.execute("SELECT received_at FROM notifications WHERE id=?",(nid,)).fetchone()[0]
            check_identity(db,{}, {},now=received+1,
                probe=lambda *_:{"decision":"NEEDS_REVIEW","issues":["UNVERIFIED"]})
            self.assertEqual(check_once(db,cfg,{},now=received+2,sender=sender)["sent"],1)
            self.assertEqual(sent,[nid])
            self.assertEqual(check_once(db,cfg,{},now=received+3,sender=sender)["sent"],0)

    def test_unmatched_webhook_explains_no_worker_job(self):
        from anime_dashboard_queries import all_jobs
        payload={"source":"nyaa","release_name":"Unmatched release 02",
                 "source_guid":"unmatched-identity","info_hash":HASH}
        status,_,body=self.request("POST","/webhook",{**payload,"token":"secret-token"})
        self.assertEqual(status,200)
        with sqlite3.connect(self.db) as db:
            result=all_jobs(db)
        self.assertEqual(result["items"][0]["status"],"IDENTIFYING")
        self.assertIn("Checking public AniDB",result["items"][0]["activity_detail"])
        self.assertIn("Activity details",self.request("GET","/jobs")[2])

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

    def test_credential_reveal_requires_valid_session_and_csrf(self):
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
                payload=json.dumps({"key":"sonarr_api_key"})
                headers={"Cookie":"ad_session="+self.session,
                         "X-CSRF-Token":self.csrf,"Content-Type":"application/json"}
                client.request("POST","/api/credential-reveal",payload,headers)
                response=client.getresponse()
                self.assertEqual(response.status,200)
                self.assertEqual(response.getheader("Cache-Control"),"no-store")
                self.assertEqual(json.loads(response.read())["value"],"sample-secret")
                client.request("POST","/api/credential-reveal",payload,
                    {"Cookie":"ad_session="+self.session,"Content-Type":"application/json"})
                response=client.getresponse()
                self.assertEqual(response.status,403)
                response.read()
                client.request("POST","/api/credential-reveal",payload,
                    {"X-CSRF-Token":self.csrf,"Content-Type":"application/json"})
                response=client.getresponse()
                self.assertEqual(response.status,401)
                response.read()
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_connection_uses_unsaved_values_without_persisting(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        from unittest.mock import patch as mocked
        with tempfile.TemporaryDirectory() as dirname:
            directory=Path(dirname)
            (directory/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (directory/"secrets.json").write_text(json.dumps({"web_token":"web-secret"}))
            os.chmod(directory/"secrets.json",0o600)
            original_settings=(directory/"settings.json").read_bytes()
            original_secrets=(directory/"secrets.json").read_bytes()
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"secret-token",config_dir=directory))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            try:
                def fake_probe(settings,secrets,service):
                    self.assertEqual(service,"sonarr")
                    self.assertEqual(settings["sonarr"]["base_url"],"https://sonarr.lab")
                    self.assertTrue(settings["sonarr"]["enabled"])
                    self.assertEqual(secrets["sonarr_api_key"],"unsaved-test-key")
                    return {"tested":True,"connected":True,"message":"Connection verified"}
                with mocked("anime_integration_connection.test_connection",
                            side_effect=fake_probe):
                    client.request("POST","/api/test-connection",json.dumps({
                        "service":"sonarr",
                        "settings":{"base_url":"https://sonarr.lab","enabled":False},
                        "credential":"unsaved-test-key"
                    }),{"Cookie":"ad_session="+self.session,
                        "X-CSRF-Token":self.csrf,"Content-Type":"application/json"})
                    response=client.getresponse()
                    self.assertEqual(response.status,200)
                    self.assertTrue(json.loads(response.read())["connected"])
                self.assertEqual((directory/"settings.json").read_bytes(),original_settings)
                self.assertEqual((directory/"secrets.json").read_bytes(),original_secrets)
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_jobs_resolve_dialog_and_safe_delete_api(self):
        status,_,page=self.request("GET","/jobs")
        self.assertEqual(status,200)
        self.assertIn('id="resolve-dialog"',page)
        self.assertIn('name="notification_id"',page)
        self.assertIn("Notification #",page)
        payload={"source":"nyaa","release_name":"Unmatched for deletion",
                 "source_guid":"delete-api-test","info_hash":HASH,
                 "token":"secret-token"}
        status,_,body=self.request("POST","/webhook",payload)
        self.assertEqual(status,200)
        nid=json.loads(body)["notification_id"]
        status,_,body=self.request("POST","/api/delete-notification",
                                 {"notification_id":nid})
        self.assertEqual(status,200)
        self.assertTrue(json.loads(body)["deleted"])
        with sqlite3.connect(self.db) as conn:
            self.assertIsNone(conn.execute("SELECT 1 FROM notifications WHERE id=?",
                                           (nid,)).fetchone())

    def test_identity_trace_requires_session_and_shows_scores(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder)
            (folder/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (folder/"secrets.json").write_text(json.dumps({"web_token":"hidden-secret"}))
            os.chmod(folder/"secrets.json",0o600)
            with sqlite3.connect(self.db) as db:
                nid=db.execute("""INSERT INTO notifications
                    (source,release_name,source_guid,info_hash,received_at,status)
                    VALUES ('nyaa','Some anime - 02','trace-key',?,1,'NEEDS_REVIEW')""",
                    ("c"*40,)).lastrowid
                from anime_unified_identity_monitor import ensure_schema
                ensure_schema(db)
                evidence={"threshold_pct":90,"title_queries":["Some anime"],
                          "tvdb_results_count":1,"candidate_scores":[
                          {"tvdb_id":"123","name":"Different title","score_pct":31,
                           "threshold_pct":90,"passed":False,"reason":"BELOW_TITLE_THRESHOLD"}],
                          "issues":["ALL_TVDB_TITLES_BELOW_THRESHOLD"]}
                db.execute("""INSERT INTO unified_identity_checks
                    (notification_id,checked_at,attempts,next_at,decision,evidence_json)
                    VALUES (?,1,1,0,'NEEDS_REVIEW',?)""",(nid,json.dumps(evidence)))
                db.commit()
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"secret-token",config_dir=folder))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            try:
                url="/api/identity-trace?notification_id="+str(nid)
                client.request("GET",url)
                response=client.getresponse()
                self.assertEqual(response.status,401)
                response.read()
                client.request("GET",url,headers={"Cookie":"ad_session="+self.session})
                response=client.getresponse()
                self.assertEqual(response.status,200)
                data=json.loads(response.read())
                self.assertEqual(data["evidence"]["candidate_scores"][0]["score_pct"],31)
                self.assertNotIn("hidden-secret",json.dumps(data))
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
