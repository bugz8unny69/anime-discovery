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

    def test_browser_keep_failure_renders_guidance_not_raw_json(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        from anime_sonarr_import import SonarrImportNeedsReview
        with tempfile.TemporaryDirectory() as directory:
            directory=Path(directory)
            (directory/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (directory/"secrets.json").write_text(json.dumps({"web_token":"web-secret"}))
            os.chmod(directory/"secrets.json",0o600)
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"secret-token",config_dir=directory))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            try:
                client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                headers={"Cookie":"ad_session="+self.session,
                         "Content-Type":"application/x-www-form-urlencoded"}
                body=urllib.parse.urlencode({"series_id":"7","action":"keep",
                                              "_csrf":self.csrf})
                with patch.object(web,"keep_series",side_effect=SonarrImportNeedsReview(
                         "EPISODE_IDENTITY_MISMATCH","Sonarr episode mapping disagrees")):
                    client.request("POST","/series-action",body,headers)
                    response=client.getresponse()
                    page=response.read().decode()
                    self.assertEqual(response.status,409)
                    self.assertIn("text/html",response.getheader("Content-Type"))
                    self.assertIn("Keep needs attention",page)
                    self.assertIn("Root Folders",page)
                    self.assertIn("Wanted",page)
                    self.assertIn("/series?id=7",page)
                    self.assertIn("EPISODE_IDENTITY_MISMATCH",page)
                    self.assertNotIn('{"error":',page)
                    # An API caller using JSON keeps the machine-readable error.
                    client.request("POST","/series-action",
                        json.dumps({"series_id":"7","action":"keep"}),{
                        "Cookie":"ad_session="+self.session,
                        "X-CSRF-Token":self.csrf,"Content-Type":"application/json"})
                    response=client.getresponse()
                    self.assertEqual(response.status,400)
                    self.assertIn("application/json",response.getheader("Content-Type"))
                    self.assertIn("Sonarr episode mapping disagrees",
                                  json.loads(response.read())["error"])
                client.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

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

    def test_identity_recheck_is_explicit_and_does_not_queue_acquisition(self):
        from anime_webhook_processing import receive
        with sqlite3.connect(self.db,isolation_level=None) as db:
            packet=receive(db,{"source":"autobrr",
                "release_name":"Example Anime S01 (Batch)",
                "source_guid":"recheck-only","info_hash":HASH})
            nid=packet["notification_id"]
            db.execute("UPDATE notifications SET status='NEEDS_REVIEW' WHERE id=?",(nid,))
        status,_,body=self.request("POST","/api/recheck-identity",
                                    {"notification_id":nid})
        self.assertEqual(status,200,body)
        self.assertEqual(json.loads(body)["status"],"IDENTIFYING")
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM daemon_jobs WHERE subject_key=?",
                (str(nid),)).fetchone()[0],0)
        status,_,body=self.request("POST","/api/recheck-identity",
                                    {"notification_id":nid})
        self.assertEqual(status,409)
        self.assertIn("Only terminal",json.loads(body)["error"])

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

    def test_webhook_token_rotation_takes_effect_without_web_restart(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as folder:
            config=Path(folder)
            (config/"settings.json").write_text(json.dumps(DEFAULT_SETTINGS))
            (config/"secrets.json").write_text(json.dumps({"web_token":"previous-token"}))
            os.chmod(config/"secrets.json",0o600)
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"previous-token",config_dir=config))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            def post(path,body,headers):
                client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
                try:
                    client.request("POST",path,json.dumps(body),
                        {"Content-Type":"application/json",**headers})
                    response=client.getresponse()
                    return response.status,response.read().decode()
                finally:
                    client.close()
            try:
                auth_headers={"Cookie":"ad_session="+self.session,"X-CSRF-Token":self.csrf}
                status,_=post("/api/credentials",
                    {"key":"web_token","clear":False,"value":"new-token"},auth_headers)
                self.assertEqual(status,200)
                original={"release_name":"Changed token episode 01","source_guid":"rotation-old",
                          "info_hash":HASH,"token":"previous-token"}
                self.assertEqual(post("/webhook",original,{})[0],401)
                original["token"]="new-token"
                original["source_guid"]="rotation-new"
                self.assertEqual(post("/webhook",original,{})[0],200)
                original["token"]=""
                original["source_guid"]="rotation-empty"
                self.assertEqual(post("/webhook?token=",original,{})[0],401)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(2)

    def test_unverified_webhook_never_sends_ntfy_until_finalized(self):
        import os
        from anime_flat_config import DEFAULT_SETTINGS
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder)
            config=json.loads(json.dumps(DEFAULT_SETTINGS))
            config["ntfy"].update({"enabled":True,"server":"https://ntfy.example",
                                    "topic":"anime","dashboard_url":"https://dashboard.example"})
            (directory/"settings.json").write_text(json.dumps(config))
            (directory/"secrets.json").write_text(json.dumps({"web_token":"web-secret"}))
            os.chmod(directory/"secrets.json",0o600)
            server=ThreadingHTTPServer(("127.0.0.1",0),
                web.app(self.db,"web-secret",config_dir=directory))
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            client=http.client.HTTPConnection("127.0.0.1",server.server_port,timeout=3)
            try:
                payload={"source":"nyaa","release_name":"[Group] Unidentified - 01",
                         "source_guid":"no-premature-ntfy","info_hash":HASH,
                         "token":"web-secret"}
                with patch("anime_ntfy.notify_best_effort",
                           side_effect=AssertionError("Premature NTFY call")) as notify:
                    client.request("POST","/webhook",json.dumps(payload),
                                   {"Content-Type":"application/json"})
                    response=client.getresponse()
                    self.assertEqual(response.status,200)
                    result=json.loads(response.read())
                    self.assertTrue(result["identification_pending"])
                    self.assertFalse(result["needs_review"])
                    notify.assert_not_called()
                with sqlite3.connect(self.db) as db:
                    self.assertEqual(db.execute("SELECT status FROM notifications WHERE id=?",
                        (result["notification_id"],)).fetchone()[0],"IDENTIFYING")
            finally:
                client.close()
                server.shutdown()
                server.server_close()
                thread.join(2)

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

    def test_jobs_status_filter_and_paging_controls(self):
        from anime_webhook_processing import receive
        with sqlite3.connect(self.db,isolation_level=None) as db:
            for n in range(24):
                receive(db,{"source":"nyaa","source_guid":"filter-"+str(n),
                    "release_name":"Example "+str(n),"info_hash":format(n+1,"040x")})
        status,_,body=self.request("GET","/api/jobs?status=IDENTIFYING&size=20&page=1")
        self.assertEqual(status,200)
        data=json.loads(body)
        self.assertEqual(data["status_filter"],"IDENTIFYING")
        self.assertEqual(data["total"],24)
        self.assertEqual(data["pages"],2)
        self.assertEqual(len(data["items"]),20)
        status,_,body=self.request("GET","/api/jobs?status=IDENTIFYING&size=20&page=2")
        self.assertEqual(status,200)
        self.assertEqual(len(json.loads(body)["items"]),4)
        status,_,page=self.request("GET","/jobs?status=IDENTIFYING&size=20&page=1")
        self.assertEqual(status,200)
        self.assertIn("job-status-filter",page)
        self.assertIn("Next",page)
        self.assertIn("status=IDENTIFYING",page)
        self.assertIn('class="jobs-table"',page)
        self.assertEqual(self.request("GET","/api/jobs?status=BOGUS")[0],400)

    def test_jobs_resolve_preserved_and_notification_delete_retired(self):
        status,_,page=self.request("GET","/jobs")
        self.assertEqual(status,200)
        self.assertIn('id="resolve-dialog"',page)
        self.assertIn('name="notification_id"',page)
        self.assertIn("Notification #",page)
        self.assertNotIn('job.can_delete',page)
        self.assertNotIn('"/api/delete-notification"',page)
        payload={"source":"nyaa","release_name":"Review must remain",
                 "source_guid":"delete-api-retired","info_hash":HASH,
                 "token":"secret-token"}
        status,_,body=self.request("POST","/webhook",payload)
        self.assertEqual(status,200)
        nid=json.loads(body)["notification_id"]
        status,_,body=self.request("POST","/api/delete-notification",
                                 {"notification_id":nid})
        self.assertEqual(status,410)
        with sqlite3.connect(self.db) as conn:
            self.assertIsNotNone(conn.execute(
                "SELECT 1 FROM notifications WHERE id=?",(nid,)).fetchone())
        status,_,data=self.request("GET","/api/jobs")
        self.assertEqual(status,200)
        matching=[item for item in json.loads(data)["items"] if item.get("id")==nid]
        self.assertEqual(len(matching),1)
        self.assertNotIn("can_delete",matching[0])


    def test_cleanup_preview_is_authenticated_and_never_deletes_media(self):
        from anime_async_daemon import enqueue
        from anime_job_management import manage
        with sqlite3.connect(self.db,isolation_level=None) as db:
            enqueue(db,"claimed_acquisition","98765",'{"notification_id":98765}')
            jid=db.execute("""SELECT id FROM daemon_jobs WHERE
                kind='claimed_acquisition' AND subject_key='98765'""").fetchone()[0]
            db.execute("UPDATE daemon_jobs SET state='NEEDS_REVIEW' WHERE id=?",(jid,))
            manage(db,jid,"cancel",expected_state="NEEDS_REVIEW",expected_attempts=0)
        status,_,body=self.request("GET","/api/cleanup-preview?job_id="+str(jid))
        self.assertIn(status,(200,409))
        if status==200:
            self.assertFalse(json.loads(body)["can_remove_torrents"])
        status,_,body=self.request("POST","/api/cleanup-confirm",
                                  {"job_id":jid,"confirmation":"REMOVE TORRENT ONLY"})
        self.assertEqual(status,409)
        self.assertNotIn("qbittorrent_password",body)

    def test_identity_review_messages_are_actionable_without_vm_logs(self):
        from anime_review_messages import describe_review
        expected={
            "NO_TVDB_SEARCH_RESULTS":"TVDB returned no matching series",
            "ALL_TVDB_TITLES_BELOW_THRESHOLD":"title-match threshold",
            "LOOKUP_AttributeError":"technical error",
        }
        for code,fragment in expected.items():
            with self.subTest(code=code):
                message=describe_review(code)
                self.assertIn(fragment,message)
                self.assertNotIn("service logs",message.lower())
        self.assertNotIn("no matching series",
                         describe_review("LOOKUP_AttributeError").lower())

    def test_manage_job_api_retry_cancel_and_visible_activity(self):
        from anime_async_daemon import enqueue
        with sqlite3.connect(self.db,isolation_level=None) as db:
            nid=db.execute("""INSERT INTO notifications
                (source,release_name,source_guid,info_hash,received_at,status)
                VALUES ('autobrr','Solo Leveling','job-actions-test',?,1,'APPROVED')""",
                (HASH,)).lastrowid
            enqueue(db,"claimed_acquisition",str(nid),'{"notification_id":1}')
            jid=db.execute("""SELECT id FROM daemon_jobs WHERE kind='claimed_acquisition'
                AND subject_key=?""",(str(nid),)).fetchone()[0]
            db.execute("""UPDATE daemon_jobs SET state='NEEDS_REVIEW',
                attempts=10,available_at=9999999999,last_error='IdentityNotReady'
                WHERE id=?""",(jid,))
        status,_,page=self.request("GET","/jobs")
        self.assertEqual(status,200)
        self.assertIn("Retry Now",page)
        self.assertIn("Cancel Job",page)
        self.assertNotIn("Next retry:",page)
        status,_,body=self.request("GET","/api/jobs")
        self.assertEqual(status,200)
        item=next(j for j in json.loads(body)["items"] if j.get("job_id")==jid)
        self.assertEqual(item["attempts"],10)
        self.assertEqual(item["last_error"],"IdentityNotReady")
        self.assertTrue(item["can_retry"])
        self.assertTrue(item["can_cancel"])
        data={"job_id":jid,"action":"retry","expected_state":"NEEDS_REVIEW",
              "expected_attempts":10}
        status,_,body=self.request("POST","/api/manage-job",data)
        self.assertEqual(status,200,body)
        self.assertEqual(json.loads(body)["state"],"READY")
        self.assertEqual(self.request("POST","/api/manage-job",data)[0],409)
        with sqlite3.connect(self.db,isolation_level=None) as db:
            db.execute("UPDATE daemon_jobs SET state='NEEDS_REVIEW' WHERE id=?",(jid,))
        data={"job_id":jid,"action":"cancel","expected_state":"NEEDS_REVIEW",
              "expected_attempts":10}
        status,_,body=self.request("POST","/api/manage-job",data)
        self.assertEqual(status,200,body)
        self.assertEqual(json.loads(body)["state"],"BLOCKED")
        status,_,body=self.request("GET","/api/jobs")
        item=next(j for j in json.loads(body)["items"] if j.get("job_id")==jid)
        self.assertEqual(item["status"],"CANCELED")
        self.assertEqual(item["last_admin_action"]["action"],"cancel")
        self.assertFalse(item["can_retry"])
        self.assertFalse(item["can_cancel"])
        with sqlite3.connect(self.db) as db:
            state=db.execute("""SELECT state,attempts,last_error FROM daemon_jobs
                WHERE id=?""",(jid,)).fetchone()
            self.assertEqual(state,("BLOCKED",10,"IdentityNotReady"))
            self.assertEqual(db.execute(
                "SELECT COUNT(*) FROM daemon_job_admin_events WHERE job_id=?",(jid,)
            ).fetchone()[0],2)

    def test_manage_job_rejects_unauthorized_csrf_and_active_lease(self):
        from anime_async_daemon import enqueue
        with sqlite3.connect(self.db,isolation_level=None) as db:
            enqueue(db,"series_gap_search","test-admin-search",'{}')
            jid=db.execute("""SELECT id FROM daemon_jobs
                WHERE kind='series_gap_search'""").fetchone()[0]
        request={"job_id":jid,"action":"cancel","expected_state":"READY",
                 "expected_attempts":0}
        client=http.client.HTTPConnection("127.0.0.1",self.port,timeout=3)
        try:
            client.request("POST","/api/manage-job",json.dumps(request),
                           {"Content-Type":"application/json"})
            response=client.getresponse()
            self.assertEqual(response.status,401)
            response.read()
            client.request("POST","/api/manage-job",json.dumps(request),
                           {"Content-Type":"application/json",
                            "Cookie":"ad_session="+self.session,
                            "X-CSRF-Token":"wrong"})
            response=client.getresponse()
            self.assertEqual(response.status,403)
            response.read()
        finally:
            client.close()
        with sqlite3.connect(self.db,isolation_level=None) as db:
            db.execute("""UPDATE daemon_jobs SET state='LEASED',lease_token='inflight',
                lease_until=9999999999,attempts=1 WHERE id=?""",(jid,))
        self.assertEqual(self.request("POST","/api/manage-job",{
            "job_id":jid,"action":"cancel","expected_state":"LEASED",
            "expected_attempts":1})[0],409)
        self.assertEqual(self.request("POST","/api/manage-job",{
            "job_id":jid,"action":"cancel","expected_state":"READY",
            "expected_attempts":0})[0],409)
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute(
                "SELECT state FROM daemon_jobs WHERE id=?",(jid,)).fetchone()[0],"LEASED")

    def test_series_management_explains_actions_and_requeues_saved_autobrr(self):
        import hashlib
        from anime_webhook_processing import receive
        trial=self.db.parent/"Anime-Trial"
        trial.mkdir()
        with sqlite3.connect(self.db,isolation_level=None) as db:
            db.execute("PRAGMA foreign_keys=ON")
            item=receive(db,{"source":"autobrr","source_guid":"reset-one",
                "release_name":"Solo Leveling S01E01","info_hash":HASH,
                "tvdb_id":389597,"anidb_id":123,"season":1,"episode":1})
            nid=item["notification_id"]
            sid=item["series_id"]
            path=trial/"TVDB-389597-S1"/"Season 01"/"S01E01.mkv"
            path.parent.mkdir(parents=True)
            path.write_bytes(b"verified trial video")
            digest=hashlib.sha256(path.read_bytes()).hexdigest()
            db.execute("""INSERT INTO torrent_recovery_records
                (notification_id,infohash,magnet_uri,staged_path,sha256,recorded_at)
                VALUES (?,?,?,?,?,1)""",(nid,HASH,
                "magnet:?xt=urn:btih:"+HASH,str(path),digest))
            db.execute("UPDATE episode_dispatch SET state='DONE' WHERE notification_id=?",(nid,))
            db.execute("UPDATE episodes SET status='STAGED' WHERE series_id=?",(sid,))
            db.execute("UPDATE daemon_jobs SET state='DONE' WHERE subject_key=?",(str(nid),))
        status,_,page=self.request("GET","/series?id="+str(sid))
        self.assertEqual(status,200)
        for expected in ("Manage series","Hide old activity",
            "Remove rejection / quarantine","Reset acquisitions",
            'action="/series-reset-acquisitions"'):
            self.assertIn(expected,page)
        self.assertNotIn('>Clear history</button>',page)
        with patch.object(web,"load_config",return_value={
                "settings":{"storage":{"trial_root":str(trial)}}}):
            self.assertEqual(self.request("POST","/series-reset-acquisitions",{
                "series_id":str(sid)})[0],409)
            status,location,_=self.request("POST","/series-reset-acquisitions",{
                "series_id":str(sid),"reset_confirm":"RESET"})
        self.assertEqual(status,303)
        self.assertEqual(location,"/jobs")
        self.assertFalse(path.exists())
        with sqlite3.connect(self.db) as db:
            self.assertEqual(db.execute("SELECT state FROM daemon_jobs WHERE subject_key=?",
                (str(nid),)).fetchone()[0],"READY")
            self.assertEqual(db.execute("SELECT count(*) FROM notifications WHERE id=?",
                (nid,)).fetchone()[0],1)
        # The Series view remains accessible even if the staged file vanished
        # without first running the reset operation.
        status,_,page=self.request("GET","/series?id="+str(sid))
        self.assertEqual(status,200)

    def test_matching_details_retry_is_inside_dialog_and_uses_existing_safe_api(self):
        status,_,page=self.request("GET","/jobs")
        self.assertEqual(status,200)
        self.assertIn('id="match-trace-retry"',page)
        self.assertIn('>Retry identification</button>',page)
        self.assertIn('openTrace(job.id,job.status==="NEEDS REVIEW"&&job.can_resolve===true)',page)
        self.assertIn('fetch("/api/recheck-identity",{method:"POST"',page)
        self.assertIn('body:JSON.stringify({notification_id:notificationId})',page)
        self.assertIn('dialog.close();',page)
        self.assertIn('if(!response.ok)throw Error(outcome.error',page)
        self.assertNotIn('textContent="Recheck identity"',page)

    def test_matching_details_renders_readable_sections_and_safe_diagnostics(self):
        status,_,page=self.request("GET","/jobs")
        self.assertEqual(status,200)
        for section in ("Decision and next step","Release and lookup",
                        "Verification checks","Candidate identities",
                        "AniDB and Anime-Lists evidence","Advanced diagnostics"):
            self.assertIn(section,page)
        self.assertIn('aria-labelledby="match-trace-title"',page)
        self.assertIn("No season comparison recorded",page)
        self.assertIn("No cross-reference diagnostic records",page)
        self.assertIn("JSON.stringify({decision:data.decision",page)
        self.assertNotIn('traceLine(body,step.step+',page)
        self.assertIn("textContent=String(text)",page)

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


class JobActionPresentationTests(unittest.TestCase):
    def test_jobs_retains_checkpoint_retry_and_resolve_with_modal_only_identity_recheck(self):
        # Assert the actual browser script, not the separate identity API.
        source=Path(__file__).with_name("anime_dashboard_pages.py").read_text()
        self.assertNotIn('textContent="Recheck identity"', source)
        self.assertIn('id="match-trace-retry"',source)
        self.assertIn('fetch("/api/recheck-identity"',source)
        self.assertNotIn('btn.textContent="Retry identification"',source)
        self.assertIn('job.can_retry', source)
        self.assertIn('job.can_resolve', source)

