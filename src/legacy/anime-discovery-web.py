"""Small writable homelab UI and Autobrr inbox using the unified database."""
import base64
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

HASH_RE = re.compile(r"^[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$")


def app(db_path, token, series_map=None, config_dir=None, *, admin_password=None):
    def aliases():
        if config_dir is not None:
            return load_config(config_dir)["settings"]["identity"]["series_map"]
        return series_map or {}

    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self, *, webhook=False):
            auth = self.headers.get("Authorization", "")
            if webhook:
                # Webhook bearer credentials must never authorize administrative routes.
                return hmac.compare_digest(auth, "Bearer " + token)
            if not admin_password or not auth.startswith("Basic "):
                return False
            try:
                credentials = base64.b64decode(auth[6:], validate=True).decode("utf-8")
                return hmac.compare_digest(credentials, "anime:" + admin_password)
            except (ValueError, UnicodeDecodeError):
                return False

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
            if not self.authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Anime Discovery"')
                self.end_headers()
                return
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
                        return self.send(200,detail_page(detail))
                    if path=="/recognized":
                        return self.send(200,recognized_page(aliases(),config_dir is not None))
                    if path=="/":
                        return self.send(200,series_page(staged_series(db,page=page,size=size),aliases()))
                    result=all_jobs(db,page=page,size=size)
                if path=="/api/jobs":
                    return self.send(200,json.dumps(result),"application/json")
                return self.send(200,jobs_page(result))
            except (ValueError,TypeError,sqlite3.Error) as exc:
                return self.send(400,str(exc),"text/plain")

        def do_POST(self):
            if not self.authorized(webhook=urlsplit(self.path).path == "/webhook"):
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Anime Discovery"')
                self.end_headers()
                return
            route = urlsplit(self.path).path
            if route not in ("/webhook", "/approve", "/series-action", "/series-bulk", "/alias", "/alias-remove", "/request-anime"):
                return self.send(404, "Not found", "text/plain")
            try:
                values = self.form()
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
    if not admin_password:
        # Transitional upgrade support: allow old installs to restart until
        # the administrator runs settings configure-credentials.
        admin_password=token
        print("WARNING: dashboard still shares webhook token; run admin settings configure-credentials immediately.",flush=True)
    elif admin_password == token:
        raise RuntimeError("Dashboard admin password must differ from webhook token")
    db_path = Path(settings["daemon"]["database_path"])
    if not db_path.is_file():
        raise RuntimeError("Database missing: " + str(db_path))
    host, port = settings["web"]["host"], settings["web"]["port"]
    print(f"Anime Discovery listening on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), app(db_path, token, settings["identity"]["series_map"], config_dir=DEFAULT_CONFIG_DIR, admin_password=admin_password)).serve_forever()


if __name__ == "__main__":
    main()
