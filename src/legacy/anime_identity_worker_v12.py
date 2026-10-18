#!/usr/bin/env python3
"""V12 isolated watch/once worker. Series evidence only; never touches torrents."""
import argparse
import fcntl
import json
import os
import sqlite3
import time
from pathlib import Path

from anime_identity_worker_v10 import DATA, init
from anime_identity_worker_v9 import rows_readonly
from anime_identity_worker_v11 import process_one
from anime_http_guard_v11 import RateLimited

DONE = {'SERIES_ALREADY_PERSISTED_EPISODE_PENDING', 'INSERTED', 'UNCHANGED', 'EVIDENCE_UPDATED'}

def retry_delay(action, attempts, retry_after=None):
    if action in DONE:
        return 0
    if retry_after is not None:
        return max(60, min(86400, float(retry_after)))
    return min(86400, 300 * 2 ** min(max(0, attempts - 1), 8))

def record_v12(db, nid, item, now):
    action = item['action']
    with sqlite3.connect(db, timeout=15) as c:
        old = c.execute('SELECT attempts FROM identity_queue WHERE notification_id=?', (nid,)).fetchone()
        attempts = (old[0] if old else 0) + 1
        next_at = now + retry_delay(action, attempts, item.get('retry_after_seconds'))
        c.execute('INSERT INTO identity_queue VALUES (?,?,?,?,?) ON CONFLICT(notification_id) DO UPDATE SET last_action=excluded.last_action, attempts=excluded.attempts, next_at=excluded.next_at, updated_at=excluded.updated_at', (nid, action, attempts, next_at, now))
    return {'attempts': attempts, 'next_at': next_at}

def pending(db, inbox, now, limit):
    rows = rows_readonly(inbox, 100)
    with sqlite3.connect(db) as conn:
        selected = []
        for nid, status in sorted(rows):
            if status != "UNTRUSTED":
                continue
            prior = conn.execute("SELECT last_action,next_at FROM identity_queue WHERE notification_id=?", (nid,)).fetchone()
            if prior and (prior[0] in DONE or prior[1] > now):
                continue
            selected.append(nid)
            if len(selected) >= limit:
                break
        return selected

def process_batch(args):
    ids = pending(args.state_db, args.inbox, time.time(), args.limit)
    report = {'version': 12, 'mode': 'WATCH' if args.watch else 'MANUAL', 'downloads_enabled': False,
              'inbox_modified': False, 'controller_modified': False, 'notifications_sent': False,
              'apply_series': True, 'items': []}
    for nid in ids:
        try:
            item = process_one(nid, args)
        except RateLimited as exc:
            item = {'notification_id': nid, 'action': 'RATE_LIMITED_RETRY', 'retry_after_seconds': exc.wait_seconds}
        except Exception as exc:
            item = {'notification_id': nid, 'action': 'ERROR_RETRY_NO_STATUS_CHANGE', 'error_type': type(exc).__name__}
        item['eligible_for_acquisition'] = False
        item['queue'] = record_v12(args.state_db, nid, item, time.time())
        report['items'].append(item)
    return report

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inbox', type=Path, default=DATA/'inbox.db')
    p.add_argument('--verified', type=Path, default=DATA/'verified-series.db')
    p.add_argument('--state-db', type=Path, default=DATA/'identity-queue-v10.db')
    p.add_argument('--rate-state', type=Path, default=DATA/'identity-http-v11.json')
    p.add_argument('--output', type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--watch', action='store_true')
    p.add_argument('--interval', type=float, default=2.0)
    p.add_argument('--poll-seconds', type=float, default=2.0)
    p.add_argument('--limit', type=int, default=5)
    args = p.parse_args()
    if not (2 <= args.interval <= 3600 and 1 <= args.poll_seconds <= 3600 and 1 <= args.limit <= 10):
        p.error('Invalid pacing/polling/limit')
    args.lookup_new = True
    args.apply_series = True
    args.state_db.parent.mkdir(parents=True, exist_ok=True)
    with open(args.state_db.with_suffix('.lock'), 'a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another identity worker is already running; no work performed', flush=True)
            return 3
        init(args.state_db)
        while True:
            report = process_batch(args)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temp = args.output.with_suffix('.tmp')
            temp.write_text(json.dumps(report, indent=2, ensure_ascii=False)+'\n')
            os.replace(temp, args.output)
            print(json.dumps({'processed': len(report['items']), 'actions': [x['action'] for x in report['items']]}), flush=True)
            if args.once:
                return 0
            time.sleep(args.poll_seconds)

if __name__ == '__main__':
    raise SystemExit(main())
