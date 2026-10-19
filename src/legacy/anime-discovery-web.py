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
from anime_series_lifecycle import action as series_action, notifications as inbox, inspect as inspect_series
from anime_flat_config import load_config

HASH_RE = re.compile(r"^[a-fA-F0-9]{40}(?:[a-fA-F0-9]{24})?$")


def app(db_path, token):
    class Handler(BaseHTTPRequestHandler):
        def send(self, status, body, content_type="text/html; charset=utf-8"):
            data = body.encode()
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def authorized(self):
            auth = self.headers.get("Authorization", "")
            if hmac.compare_digest(auth, "Bearer " + token):
                return True
            if auth.startswith("Basic "):
                try:
                    credentials = base64.b64decode(auth[6:], validate=True).decode("utf-8")
                    return hmac.compare_digest(credentials, "anime:" + token)
                except (ValueError, UnicodeDecodeError):
                    return False
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
            return {k: v[-1] for k, v in parse_qs(raw).items()}


        def do_GET(self):
            if not self.authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Anime Discovery"')
                self.end_headers()
                return
            route = urlsplit(self.path)
            if route.path not in ("/", "/series", "/health"):
                return self.send(404, "Not found", "text/plain")
            if route.path == "/health":
                return self.send(200, '{"status":"running"}', "application/json")
            esc = lambda x: html.escape(str(x), quote=True)
            def table(headers, records):
                head = "".join("<th>"+esc(v)+"</th>" for v in headers)
                rows = "".join("<tr>"+"".join("<td>"+esc(v)+"</td>" for v in record)+"</tr>"
                               for record in records)
                return "<table><thead><tr>"+head+"</tr></thead><tbody>"+rows+"</tbody></table>"
            style = """<!doctype html><html lang="en"><meta charset="utf-8">
                <meta name="viewport" content="width=device-width,initial-scale=1">
                <title>Anime Discovery</title>
                <style>
                body{font:16px system-ui;margin:0 auto;max-width:1150px;padding:2rem;
                  color:#e7edf9;background:#101725;line-height:1.5}
                h1,h2{color:#fff}a{color:#96c7ff}
                section{background:#1c2739;border:1px solid #344459;border-radius:12px;
                  padding:1.2rem;margin:1.1rem 0;overflow:auto}
                table{border-collapse:collapse;width:100%;font-size:.93rem}
                th,td{text-align:left;padding:.55rem;border-bottom:1px solid #38475a}
                input,select,button{padding:.6rem;margin:.25rem;background:#25364a;
                  border:1px solid #526881;border-radius:6px;color:white}
                button{cursor:pointer;background:#20568c}
                form{display:flex;gap:.25rem;flex-wrap:wrap;align-items:center}
                .muted{color:#a6b5c9}
                </style><body><header><h1>Anime Discovery</h1>
                <a href="/">Dashboard</a></header>"""
            with self.database() as db:
                if route.path == "/series":
                    ids = parse_qs(route.query).get("id", [])
                    if len(ids)!=1:
                        raise ValueError("Specify series id")
                    try:
                        detail = inspect_series(db, int(ids[0]))
                    except ValueError as exc:
                        return self.send(404, str(exc), "text/plain")
                    series = detail["series"]
                    body = style + "<section><h2>"+esc(series[1])+"</h2><p>TVDB "+esc(series[2])+" | "+esc(series[3])+"</p>"
                    body += "<p>Rejection block: "+esc(detail["rejected"])+"</p>"
                    body += table(("Season","Episode","State"),detail["episodes"])
                    body += "</section><section><h2>Release history</h2>"
                    body += table(("Notification","Release","Season","Episode","Dispatch","Job","Staged media"),detail["releases"])
                    body += "</section></body></html>"
                    return self.send(200,body)
                events = inbox(db)
                series = db.execute("SELECT id,title,external_id,status FROM series ORDER BY id DESC LIMIT 100").fetchall()
                jobs = dict(db.execute("SELECT state,count(*) FROM daemon_jobs GROUP BY state").fetchall())
            shows = []
            for sid,title,tvdb,status in series:
                shows.append((str(sid),title,tvdb,status))
            linked = "".join("<tr><td><a href='/series?id="+str(row[0])+"'>"+str(row[0])+"</a></td>"+
                "".join("<td>"+esc(v)+"</td>" for v in row[1:])+"</tr>" for row in shows)
            body = style + "<p>Daemon jobs: "+esc(jobs)+"</p>"
            body += "<section><h2>Series</h2><table><tr><th>ID</th><th>Title</th><th>TVDB</th><th>Status</th></tr>"+linked+"</table>"
            body += """<h3>Manage series</h3>
                <form method="post" action="/series-action">
                <input name="series_id" type="number" min="1" placeholder="Series ID" required>
                <select name="action"><option value="reject">Reject</option>
                <option value="clear-history">Clear History</option>
                <option value="reset">Reset</option></select>
                <button>Apply</button></form>
                <p class="muted">Reject blocks queued work; Clear History hides earlier
                notifications without lifting the block; Reset allows future acquisitions.</p></section>"""
            body += "<section><h2>Autobrr inbox</h2>"
            body += table(("ID","Source","Release","Hash","Notification","Dispatch","Job"),events)
            body += """</section><section><h2>Approve an inbox release</h2>
                <p class="muted">Only needed if Autobrr didn't send verified TVDB/AniDB
                and episode identifiers.</p>
                <form method="post" action="/approve">
                <input name="notification_id" type="number" min="1" placeholder="Notification ID" required>
                <input name="tvdb_id" type="number" min="1" placeholder="TVDB ID" required>
                <input name="anidb_id" type="number" min="1" placeholder="AniDB ID" required>
                <input name="season" type="number" min="1" placeholder="Season" required>
                <input name="episode" type="number" min="1" placeholder="Episode" required>
                <input name="magnet_uri" placeholder="Optional magnet URI" size="45">
                <button>Approve and queue</button></form></section></body></html>"""
            return self.send(200,body)

        def do_POST(self):
            if not self.authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Anime Discovery"')
                self.end_headers()
                return
            route = urlsplit(self.path).path
            if route not in ("/webhook", "/approve", "/series-action"):
                return self.send(404, "Not found", "text/plain")
            try:
                values = self.form()
                with self.database() as db:
                    if route == "/webhook":
                        result = receive(db, values)
                    elif route == "/series-action":
                        result = series_action(db, int(values["series_id"]), str(values["action"]))
                    else:
                        result = approve(db, values["notification_id"], values)
                if route != "/webhook" and self.headers.get("Content-Type","").startswith("application/x-www-form-urlencoded"):
                    destination = "/series?id=" + str(result["series_id"]) if route == "/series-action" else "/"
                    self.send_response(303)
                    self.send_header("Location", destination)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                else:
                    self.send(200,json.dumps(result),"application/json")
            except (ValueError,KeyError,TypeError,sqlite3.Error,json.JSONDecodeError) as exc:
                self.send(400,json.dumps({"error":str(exc)}),"application/json")
    return Handler


def main():
    config = load_config()
    settings, secrets = config["settings"], config["secrets"]
    token = secrets.get("web_token")
    if not token:
        raise RuntimeError("Set web_token in /etc/anime-discovery/secrets.json")
    db_path = Path(settings["daemon"]["database_path"])
    if not db_path.is_file():
        raise RuntimeError("Database missing: " + str(db_path))
    host, port = settings["web"]["host"], settings["web"]["port"]
    print(f"Anime Discovery listening on {host}:{port}", flush=True)
    ThreadingHTTPServer((host, port), app(db_path, token)).serve_forever()


if __name__ == "__main__":
    main()
