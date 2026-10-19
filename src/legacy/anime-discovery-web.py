"""Small writable homelab UI and Autobrr inbox using the unified database."""
import argparse
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

from anime_acquisition_enqueue import enqueue_claimed_acquisition

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
            if urlsplit(self.path).path != "/":
                return self.send(404, "Not found", "text/plain")
            with self.database() as db:
                notifications = db.execute(
                    "SELECT id,source,release_name,info_hash,status FROM notifications ORDER BY id DESC LIMIT 100").fetchall()
                series = db.execute(
                    "SELECT id,title,external_id,status FROM series ORDER BY id DESC LIMIT 100").fetchall()
                jobs = db.execute(
                    "SELECT state,count(*) FROM daemon_jobs GROUP BY state").fetchall()
            esc = lambda x: html.escape(str(x), quote=True)
            rows = "".join("<tr>" + "".join("<td>" + esc(v) + "</td>" for v in row) + "</tr>" for row in notifications)
            shows = "".join("<tr>" + "".join("<td>" + esc(v) + "</td>" for v in row) + "</tr>" for row in series)
            body = """<!doctype html><meta charset="utf-8"><title>Anime Discovery</title>
            <style>body{font:16px system-ui;max-width:1100px;margin:2rem auto;padding:1rem;background:#141722;color:#eee}
            table{border-collapse:collapse;width:100%}td,th{padding:.6rem;border-bottom:1px solid #555;text-align:left}
            input{padding:.5rem;margin:.3rem}button{padding:.6rem}</style>
            <h1>Anime Discovery</h1><p>Jobs: """ + esc(dict(jobs)) + """</p>
            <h2>Series</h2><table><tr><th>ID</th><th>Title</th><th>TVDB</th><th>Status</th></tr>""" + shows + """</table>
            <h2>Autobrr inbox</h2><table><tr><th>ID</th><th>Source</th><th>Release</th><th>Hash</th><th>Status</th></tr>""" + rows + """</table>
            <h2>Approve notification and queue acquisition</h2>
            <p>Use verified TVDB/AniDB IDs and episode numbering. Existing series are reused.</p>
            <form method="post" action="/approve">
            <input name="notification_id" type="number" placeholder="Notification ID" required>
            <input name="tvdb_id" type="number" placeholder="TVDB ID" required>
            <input name="anidb_id" type="number" placeholder="AniDB ID" required>
            <input name="season" type="number" min="1" placeholder="Season" required>
            <input name="episode" type="number" min="1" placeholder="Episode" required>
            <input name="magnet_uri" placeholder="Magnet URI" size="55" required>
            <button>Approve and queue</button></form>
            <p>Use an API client with Authorization: Bearer TOKEN for requests; browser login uses username anime and password TOKEN.</p>"""
            self.send(200, body)

        def do_POST(self):
            if not self.authorized():
                self.send_response(401)
                self.send_header("WWW-Authenticate", 'Basic realm="Anime Discovery"')
                self.end_headers()
                return
            route = urlsplit(self.path).path
            if route not in ("/webhook", "/approve"):
                return self.send(404, "Not found", "text/plain")
            try:
                values = self.form()
                with self.database() as db:
                    if route == "/webhook":
                        source = str(values.get("source", "autobrr"))[:100]
                        title = str(values.get("release_name") or values.get("name") or "").strip()
                        guid = str(values.get("source_guid") or values.get("guid") or "").strip()
                        infohash = str(values.get("info_hash") or values.get("hash") or "").lower()
                        if not title or not guid or not HASH_RE.fullmatch(infohash):
                            raise ValueError("release_name, source_guid, info_hash required")
                        db.execute("""INSERT OR IGNORE INTO notifications
                            (source,release_name,source_guid,info_hash,received_at)
                            VALUES (?,?,?,?,?)""", (source,title,guid,infohash,int(time.time())))
                        result = {"received": True}
                    else:
                        nid = int(values["notification_id"])
                        tvdb = str(int(values["tvdb_id"]))
                        anidb = str(int(values["anidb_id"]))
                        season, episode = int(values["season"]), int(values["episode"])
                        magnet = str(values["magnet_uri"])
                        if min(nid, int(tvdb), int(anidb), season, episode) <= 0:
                            raise ValueError("Positive IDs and episode numbers required")
                        db.execute("BEGIN IMMEDIATE")
                        try:
                            notification = db.execute(
                                "SELECT release_name,info_hash FROM notifications WHERE id=?", (nid,)).fetchone()
                            if not notification:
                                raise ValueError("Notification not found")
                            existing = db.execute("SELECT id FROM series WHERE source='tvdb' AND external_id=?", (tvdb,)).fetchone()
                            if existing:
                                sid = existing[0]
                            else:
                                sid = db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb',?,?)",
                                                 (tvdb, notification[0])).lastrowid
                            evidence = json.dumps({"manual_approval": True, "tvdb_id": tvdb,
                                                   "anidb_id": anidb, "season": season, "episode": episode}, sort_keys=True)
                            db.execute("""INSERT INTO verified_series_identity
                                (notification_id,anidb_id,tvdb_id,mapping_source,decision,
                                episode_identity_verified,eligible_for_acquisition,evidence_json,evidence_sha256)
                                VALUES (?,?,?,'manual','VERIFIED',1,1,?,?)""",
                                (nid,anidb,tvdb,evidence,hashlib.sha256(evidence.encode()).hexdigest()))
                            db.execute("""INSERT INTO episode_verification_v16
                                (notification_id,evaluated_at,decision,verified,evidence_json)
                                VALUES (?,?,'VERIFIED',1,?)""",(nid,time.time(),evidence))
                            db.execute("""INSERT INTO episode_approval_queue
                                (notification_id,decision,season,episode)
                                VALUES (?,'AUTO_APPROVED',?,?)""",(nid,season,episode))
                            db.execute("""INSERT INTO episode_dispatch
                                (notification_id,series_id,season,episode,state)
                                VALUES (?,?,?,?,'CLAIMED')""",(nid,sid,season,episode))
                            db.commit()
                        except BaseException:
                            db.rollback()
                            raise
                        queued = enqueue_claimed_acquisition(
                            db,nid,infohash=notification[1],magnet_uri=magnet,
                            title=notification[0],tvdb_id=tvdb)
                        result = {"queued": queued, "notification_id": nid}
                self.send(200,json.dumps(result),"application/json")
            except (ValueError,KeyError,TypeError,sqlite3.Error,json.JSONDecodeError) as exc:
                self.send(400,json.dumps({"error":str(exc)}),"application/json")
    return Handler


def main():
    parser = argparse.ArgumentParser(description="Anime Discovery homelab web UI and webhook")
    parser.add_argument("--db", type=Path, default=Path("/var/lib/anime-discovery/anime-discovery.db"))
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--token", required=True, help="Shared bearer token for dashboard and webhook")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error("Database missing: initialize with admin new-database")
    if not args.token:
        parser.error("Token cannot be empty")
    print(f"Anime Discovery listening on {args.host}:{args.port}",flush=True)
    ThreadingHTTPServer((args.host,args.port),app(args.db,args.token)).serve_forever()


if __name__ == "__main__":
    main()
