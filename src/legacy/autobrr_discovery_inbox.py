"""Opt-in localhost-only, authenticated, discovery-only release inbox.

Not an autobrr-native schema parser: configure autobrr's custom webhook body to
match the documented JSON contract. Payload is untrusted and never authorizes
metadata approval or acquisition. Python 3.11, stdlib only.
"""
import hashlib
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from anime_config_runtime import get as config_get, data_path
import re
import sqlite3
import threading
import time
from urllib.parse import urlsplit

MAX_BODY = 8192
MAX_ITEMS = 2000
HASH_RE = re.compile(r'^[a-fA-F0-9]{40}$')
ALLOWED = {'nyaa', 'prowlarr'}

class InboxError(ValueError):
    pass

def validate(payload):
    if not isinstance(payload, dict) or set(payload) != {'source', 'release_name', 'source_guid', 'info_hash'}:
        raise InboxError('SCHEMA_MISMATCH')
    source = payload['source']
    name = payload['release_name']
    guid = payload['source_guid']
    infohash = payload['info_hash']
    if source not in ALLOWED:
        raise InboxError('SOURCE_NOT_ALLOWED')
    if not isinstance(name, str) or not 1 <= len(name) <= 400 or any(ord(c) < 32 for c in name):
        raise InboxError('INVALID_RELEASE_NAME')
    if not isinstance(guid, str) or not 1 <= len(guid) <= 500 or any(ord(c) < 32 for c in guid):
        raise InboxError('INVALID_GUID')
    if not isinstance(infohash, str) or not HASH_RE.fullmatch(infohash):
        raise InboxError('INVALID_INFO_HASH')
    return source, name, guid, infohash.lower()

class Inbox:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()
        if not self.path.parent.is_dir():
            raise InboxError('INBOX_DIRECTORY_MISSING')
        if self.path.is_symlink():
            raise InboxError('SYMLINK_DATABASE_FORBIDDEN')
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS notifications (id INTEGER PRIMARY KEY, source TEXT NOT NULL, release_name TEXT NOT NULL, source_guid TEXT NOT NULL, info_hash TEXT NOT NULL, received_at INTEGER NOT NULL, status TEXT NOT NULL DEFAULT "UNTRUSTED", UNIQUE(source, source_guid))')
    def connect(self):
        db = sqlite3.connect(str(self.path), timeout=5)
        db.execute('PRAGMA busy_timeout=5000')
        return db
    def receive(self, payload):
        source, name, guid, infohash = validate(payload)
        from anime_v19_rejection_guard import blocked
        if blocked(infohash):
            return 'rejected_blocked'
        with self.lock:
            with self.connect() as db:
                count = db.execute('SELECT count(*) FROM notifications').fetchone()[0]
                existing = db.execute('SELECT info_hash, release_name FROM notifications WHERE source=? AND source_guid=?', (source, guid)).fetchone()
                if existing:
                    if existing != (infohash, name):
                        raise InboxError('GUID_REUSED_WITH_DIFFERENT_RELEASE')
                    return 'duplicate'
                if count >= MAX_ITEMS:
                    raise InboxError('INBOX_CAPACITY_REACHED')
                db.execute('INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at) VALUES (?,?,?,?,?)', (source,name,guid,infohash,int(time.time())))
                return 'queued_untrusted'

def make_handler(inbox, token):
    if not isinstance(token, str) or len(token) < 32:
        raise InboxError('TOKEN_TOO_SHORT')
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format, *args):
            pass  # No tokens, URLs or release names in access logs.
        def reply(self, code, status):
            body = json.dumps({'status': status}, separators=(',', ':')).encode()
            self.send_response(code)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Cache-Control', 'no-store')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def do_POST(self):
            if urlsplit(self.path).path != '/v1/release' or self.path != '/v1/release':
                return self.reply(404, 'NOT_FOUND')
            if self.headers.get('Content-Type', '').split(';')[0].strip().lower() != 'application/json':
                return self.reply(415, 'JSON_REQUIRED')
            raw_len = self.headers.get('Content-Length', '')
            if not raw_len.isdecimal() or not 0 < int(raw_len) <= MAX_BODY or self.headers.get('Transfer-Encoding'):
                return self.reply(413, 'INVALID_LENGTH')
            try:
                raw = self.rfile.read(int(raw_len))
                data = json.loads(raw.decode('utf-8'))
                if not isinstance(data, dict):
                    return self.reply(422, 'INVALID_PAYLOAD')
                auth = self.headers.get('Authorization', '')
                header_ok = hmac.compare_digest(auth.encode(), ('Bearer '+token).encode())
                supplied = data.pop('token', None)
                body_ok = isinstance(supplied, str) and hmac.compare_digest(supplied.encode(), token.encode())
                if not (header_ok or body_ok):
                    return self.reply(401, 'UNAUTHORIZED')
                result = inbox.receive(data)
            except RuntimeError:
                return self.reply(503, 'REJECTION_STATE_UNAVAILABLE')
            except (ValueError, UnicodeError, sqlite3.Error) as exc:
                if isinstance(exc, InboxError):
                    return self.reply(422, str(exc))
                return self.reply(422, 'INVALID_PAYLOAD')
            return self.reply(202 if result == 'queued_untrusted' else 200, result)
    return Handler

def main():
    db_path = data_path('inbox.db')
    port = config_get('inbox.bind_port')
    host = config_get('inbox.bind_host')
    token = os.environ.get('AUTOBRR_DISCOVERY_INBOX_TOKEN', '')
    if db_path.resolve() == data_path('controller.db').resolve():
        raise InboxError('Controller database forbidden')
    # Never initialize a fresh inbox during a path migration.
    if not db_path.is_file():
        raise InboxError(f'INBOX_DATABASE_MISSING: {db_path}; migrate existing database first')
    handler = make_handler(Inbox(db_path), token)
    server = ThreadingHTTPServer((host, port), handler)
    print(f'Discovery-only inbox listening on {host}:{port} (no torrent actions)', flush=True)
    server.serve_forever()

if __name__ == '__main__':
    main()
