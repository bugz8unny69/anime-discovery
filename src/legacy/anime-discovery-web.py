"""Small writable homelab UI and Autobrr inbox using the unified database."""
import hashlib
import hmac
import html
import json
import re
import sqlite3
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from anime_webhook_processing import approve, receive
from anime_series_lifecycle import action as series_action, bulk_action, keep as keep_series, inspect as inspect_series
from anime_dashboard_queries import staged_series, all_jobs
from anime_dashboard_pages import series_page, jobs_page, recognized_page, detail_page
from anime_flat_config import load_config, DEFAULT_CONFIG_DIR
from anime_series_aliases import add_alias, remove_alias
from anime_shared_discovery import identity_for_request, schedule
import anime_dashboard_auth as dashboard_auth
from http.cookies import SimpleCookie

HASH_RE = re.compile(r"^[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$")


def app(db_path, token, series_map=None, config_dir=None, *, admin_password=None):
    def aliases():
        if config_dir is not None:
            return load_config(config_dir)["settings"]["identity"]["series_map"]
        return series_map or {}

    class Handler(BaseHTTPRequestHandler):
        login_attempts = {}
        def send(self, status, body, content_type="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def cookie_session(self):
            header=self.headers.get("Cookie","")
            if len(header)>2048:
                return None
            cookie=SimpleCookie()
            try:
                cookie.load(header)
                return cookie["ad_session"].value if "ad_session" in cookie else None
            except Exception:
                return None

        def authorized(self, *, webhook=False):
            if webhook:
                # Webhook bearer token is not an administrator credential.
                return hmac.compare_digest(
                    self.headers.get("Authorization",""),"Bearer "+token)
            return dashboard_auth.valid_session(self.cookie_session())

        def csrf_token(self):
            session=self.cookie_session()
            return hashlib.sha256(session.encode()).hexdigest() if session else ""

        def check_csrf(self, values):
            supplied=self.headers.get("X-CSRF-Token") or values.get("_csrf","")
            return hmac.compare_digest(str(supplied),self.csrf_token())

        def login_page(self, error=""):
            warning=('<p role="alert" class="error">'+html.escape(error)+'</p>') if error else ""
            return """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Anime Discovery · Sign in</title>
<style>
:root{color-scheme:dark}body{margin:0;min-height:100vh;display:grid;place-items:center;
font:16px system-ui,sans-serif;background:#101827;color:#e8eef7}
main{width:min(92vw,380px);padding:2.2rem;background:#1b2739;border:1px solid #33455e;
border-radius:16px;box-shadow:0 16px 50px #0005}h1{margin:0 0 .5rem}
p{color:#aebed0}label{display:block;margin:1.3rem 0 .35rem}
input,button{box-sizing:border-box;width:100%;padding:.8rem;border-radius:9px;font:inherit}
input{background:#101827;color:white;border:1px solid #52647b}
button{background:#4f9df8;color:#101827;border:0;margin-top:1.6rem;cursor:pointer;font-weight:700}
.error{color:#ffb7ba}</style></head><body><main><h1>Anime Discovery</h1>
<p>Sign in to your dashboard</p>"""+warning+"""
<form method="post" action="/login"><label for="username">Username</label>
<input id="username" name="username" autocomplete="username" required>
<label for="password">Password</label>
<input id="password" name="password" type="password" autocomplete="current-password" required>
<button type="submit">Sign in</button></form></main></body></html>"""

        def redirect(self, destination, *, cookie=None):
            self.send_response(303)
            self.send_header("Location",destination)
            self.send_header("Cache-Control","no-store")
            if cookie is not None:
                self.send_header("Set-Cookie",cookie)
            self.send_header("Content-Length","0")
            self.end_headers()

        def session_cookie(self, token, *, clear=False):
            # The reverse proxy should set X-Forwarded-Proto only after TLS
            # termination. An untrusted header can only strengthen Secure.
            secure="; Secure" if self.headers.get("X-Forwarded-Proto","").lower()=="https" else ""
            if clear:
                return "ad_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"+secure
            return "ad_session="+token+"; Path=/; HttpOnly; SameSite=Lax; Max-Age=43200"+secure

        def with_csrf(self, page):
            hidden='<input type="hidden" name="_csrf" value="'+self.csrf_token()+'">'
            return re.sub(r"(<form\\b[^>]*>)",lambda match:match.group(1)+hidden,page,
                          flags=re.IGNORECASE)

        def database(self):
            db = sqlite3.connect(db_path, isolation_level=None, timeout=10)
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA busy_timeout=10000")
            return db

        def form(self):
            size = int(self.headers.get("Content-Length", "0"))
            if size < 1 or size > 65536:
                raise ValueError("Invalid request size")
            raw = self.rfile.read(size).decode("utf-8")
            if self.headers.get("Content-Type", "").startswith("application/json"):
                obj = json.loads(raw)
                if not isinstance(obj, dict):
                    raise ValueError("Expected JSON object")
                return obj
            return {k: (v if k=="series_ids" else v[-1]) for k, v in parse_qs(raw).items()}


        def do_GET(self):
            route=urlsplit(self.path)
            if route.path=="/login":
                if self.authorized():
                    return self.redirect("/")
                return self.send(200,self.login_page())
            if not self.authorized():
                if route.path.startswith("/api/"):
                    return self.send(401,json.dumps({"error":"Authentication required"}),"application/json")
                return self.redirect("/login")
            route=urlsplit(self.path)
            path=route.path
            if path=="/health":
                return self.send(200,'{"status":"running"}',"application/json")
            if path not in ("/","/jobs","/api/jobs","/recognized","/series"):
                return self.send(404,"Not found","text/plain")
            try:
                params=parse_qs(route.query)
                page=params.get("page",[1])[-1]
                size=params.get("size",[20])[-1]
                with self.database() as db:
                    if path=="/series":
                        ids=params.get("id",[])
                        if len(ids)!=1:
                            raise ValueError("Specify one series ID")
                        detail=inspect_series(db,int(ids[0]))
                        return self.send(200,self.with_csrf(detail_page(detail)))
                    if path=="/recognized":
                        return self.send(200,self.with_csrf(recognized_page(aliases(),config_dir is not None)))
                    if path=="/":
                        return self.send(200,self.with_csrf(series_page(staged_series(db,page=page,size=size),aliases())))
                    result=all_jobs(db,page=page,size=size)
                if path=="/api/jobs":
                    return self.send(200,json.dumps(result),"application/json")
                return self.send(200,self.with_csrf(jobs_page(result)))
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,str(exc),"text/plain")

        def do_POST(self):
            route=urlsplit(self.path).path
            if route=="/login":
                try:
                    values=self.form()
                    client=self.client_address[0]
                    now=time.monotonic()
                    recent=[t for t in self.login_attempts.get(client,[]) if now-t<300]
                    if len(recent)>=10:
                        self.login_attempts[client]=recent
                        return self.send(429,self.login_page("Too many attempts. Try again later."))
                    if dashboard_auth.verify(str(values.get("username","")),
                                             str(values.get("password",""))):
                        self.login_attempts.pop(client,None)
                        return self.redirect("/",cookie=self.session_cookie(
                            dashboard_auth.session_token(ttl=43200)))
                    recent.append(now)
                    self.login_attempts[client]=recent
                    return self.send(401,self.login_page("Invalid username or password"))
                except (ValueError,TypeError):
                    return self.send(400,self.login_page("Invalid sign-in request"))
            if not self.authorized(webhook=route=="/webhook"):
                return self.send(401,json.dumps({"error":"Authentication required"}),"application/json")
            if route=="/logout":
                values=self.form()
                if not self.check_csrf(values):
                    return self.send(403,"Invalid CSRF token","text/plain")
                dashboard_auth.revoke_all()
                return self.redirect("/login",cookie=self.session_cookie("",clear=True))
            if route!="/webhook":
                # Require a session-bound CSRF token for both form and JSON mutations.
                supplied=self.headers.get("X-CSRF-Token","")
                if not supplied:
                    # Read body only once later via self.form().
                    # HTML forms carry the token in a hidden field.
                    values=self.form()
                    if not self.check_csrf(values):
                        return self.send(403,"Invalid CSRF token","text/plain")
                    self._cached_form=values
                elif not self.check_csrf({}):
                    return self.send(403,"Invalid CSRF token","text/plain")
            route = urlsplit(self.path).path
            if route not in ("/webhook", "/approve", "/series-action", "/series-bulk", "/alias", "/alias-remove", "/request-anime"):
                return self.send(404, "Not found", "text/plain")
            try:
                values = getattr(self,"_cached_form",None) or self.form()
                with self.database() as db:
                    if route == "/webhook":
                        result = receive(db, values, series_map=aliases(),
                            gap_search_enabled=(load_config(config_dir)["settings"]["prowlarr"]["enabled"] if config_dir else False))
                    elif route == "/request-anime":
                        config=load_config(config_dir) if config_dir else {"settings":{"prowlarr":{"enabled":False}}}
                        if not config["settings"]["prowlarr"]["enabled"]:
                            raise ValueError("Configure Prowlarr in settings before requesting anime")
                        identity=identity_for_request(aliases(),
                            title=values.get("title") or None,
                            tvdb_id=values.get("tvdb_id") or None,
                            anidb_id=values.get("anidb_id") or None)
                        result=schedule(db,**identity,season=int(values.get("season",1)),origin="manual")
                    elif route in ("/alias", "/alias-remove"):
                        if config_dir is None:
                            raise ValueError("Alias editor requires settings directory")
                        if route == "/alias":
                            result = add_alias(config_dir, values["alias"], values["tvdb_id"],
                                               values["anidb_id"], values.get("season",1))
                        else:
                            result = remove_alias(config_dir, values["alias"])
                    elif route == "/series-action":
                        result = (keep_series(db, int(values["series_id"]), load_config(config_dir)["settings"], load_config(config_dir)["secrets"]) if values["action"]=="keep" and config_dir is not None else series_action(db, int(values["series_id"]), str(values["action"])))
                    elif route == "/series-bulk":
                        result = bulk_action(db, values.get("series_ids", []), str(values["action"]))
                    else:
                        result = approve(db, values["notification_id"], values)
                if route == "/webhook" and not result.get("duplicate") and not result.get("queued") and config_dir is not None:
                    from anime_ntfy import notify_best_effort
                    cfg=load_config(config_dir)
                    notified=notify_best_effort(cfg["settings"],cfg["secrets"],result["notification_id"],
                                       values.get("release_name") or values.get("torrentName") or "Unknown release")
                    if notified:
                        from anime_ntfy_monitor import mark_sent
                        with self.database() as notify_db:
                            mark_sent(notify_db,result["notification_id"])
                if route != "/webhook" and self.headers.get("Content-Type","").startswith("application/x-www-form-urlencoded"):
                    destination = "/series?id=" + str(result["series_id"]) if route == "/series-action" else ("/?page="+str(values.get("return_page",1))+"&size="+str(values.get("return_size",20)) if route=="/series-bulk" else ("/jobs" if route in ("/approve","/request-anime") else "/recognized"))
                    self.send_response(303)
                    self.send_header("Location", destination)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self.send(200,json.dumps(result),"application/json")
            except (ValueError,KeyError,TypeError,sqlite3.Error,json.JSONDecodeError,RuntimeError) as exc:
                self.send(400,json.dumps({"error":str(exc)}),"application/json")
    return Handler


def main():
    config = load_config()
    settings, secrets = config["settings"], config["secrets"]
    token = secrets.get("web_token")
    if not token:
        raise RuntimeError("Set web_token in /etc/anime-discovery/secrets.json")
    admin_password = secrets.get("admin_password")
    # One-time migration of existing installations. No webhook-token fallback.
    # Once initialized, the hashed authentication store is authoritative.
    if dashboard_auth.read() is None:
        if not admin_password or admin_password==token:
            raise RuntimeError("Dashboard administrator password must be initialized locally")
        dashboard_auth.initialize_legacy(admin_password)
    db_path = Path(settings["daemon"]["database_path"])
    if not db_path.is_file():
        raise RuntimeError("Database missing: " + str(db_path))
    host, port = settings["web"]["host"], settings["web"]["port"]
    print(f"Anime Discovery listening on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), app(db_path, token, settings["identity"]["series_map"], config_dir=DEFAULT_CONFIG_DIR, admin_password=admin_password)).serve_forever()


if __name__ == "__main__":
    main()
