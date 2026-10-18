#!/usr/bin/env python3
"""Manual V11 identity queue processing with persistent per-request pacing.

No inbox status changes, notifications, torrent operations or episode approvals.
"""
import argparse
import fcntl
import json
import os
import sqlite3
import time
from pathlib import Path

from anime_http_guard_v11 import protected, RateLimited
from anime_identity_worker_v10 import DATA, init, pending, record
from anime_identity_worker_v9 import saved_readonly
from anime_identity_decision_v7 import decide
from anime_identity_persistence_v8 import persist


def network_runner(notification_id):
    from anime_identity_episode_v6 import run_v3, audit, inspect, data_path, config_get, tvdb_token, TVDB_URL, request_json
    from urllib.parse import urlencode
    report = run_v3(notification_id)
    if report.get('issues'):
        return report
    report = audit(report, data_path('anime-lists.xml').read_bytes())
    if report.get('issues') or len(report.get('episode_audit') or []) != 1:
        return report
    key = (config_get('tvdb.api_key') or '').strip() if config_get('tvdb.enabled') else ''
    if not key:
        raise ValueError('TVDB unavailable')
    token = tvdb_token(key, os.getenv('ANIME_TVDB_PIN', ''))
    return inspect(report, lambda sid, page: request_json(
        f'{TVDB_URL}/series/{int(sid)}/episodes/default?' + urlencode({'page': page}), bearer=token))


def process_one(nid, args):
    saved = saved_readonly(args.verified, nid)
    if saved:
        if saved[3] or saved[4]:
            raise ValueError('Stored identity unexpectedly authorizes episode acquisition')
        return {'notification_id': nid, 'action': 'SERIES_ALREADY_PERSISTED_EPISODE_PENDING',
                'anidb_id': saved[0], 'tvdb_id': saved[1], 'eligible_for_acquisition': False}
    if not args.lookup_new:
        return {'notification_id': nid, 'action': 'NEW_IDENTITY_LOOKUP_PENDING_RATE_LIMIT_INTEGRATION',
                'eligible_for_acquisition': False}
    # This also protects login, searches, extended lookups and paginated episodes.
    with protected(args.rate_state, args.interval) as guard:
        report = network_runner(nid)
        decision = decide(report)
        item = {'notification_id': nid, 'decision': decision['decision'],
                'issues': decision.get('issues', []), 'eligible_for_acquisition': False,
                'http_requests': guard.count}
        if decision['series_identity_verified'] and decision.get('tvdb_episode_exists'):
            saved_result = persist(args.verified, decision, apply=args.apply_series)
            item.update(action=saved_result['action'], anidb_id=saved_result['anidb_id'],
                        tvdb_id=saved_result['tvdb_id'])
        else:
            item['action'] = 'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE'
        return item

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inbox', type=Path, default=DATA/'inbox.db')
    p.add_argument('--verified', type=Path, default=DATA/'verified-series.db')
    p.add_argument('--state-db', type=Path, default=DATA/'identity-queue-v10.db')
    p.add_argument('--rate-state', type=Path, default=DATA/'identity-http-v11.json')
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--lookup-new', action='store_true')
    p.add_argument('--apply-series', action='store_true')
    p.add_argument('--interval', type=float, default=2.0)
    p.add_argument('--limit', type=int, default=5)
    args = p.parse_args()
    if not 1 <= args.limit <= 10 or not 2 <= args.interval <= 3600:
        p.error('limit must be 1..10 and interval at least 2 seconds')
    if args.apply_series and not args.lookup_new:
        p.error('--apply-series requires --lookup-new')
    args.state_db.parent.mkdir(parents=True, exist_ok=True)
    with open(args.state_db.with_suffix('.lock'), 'a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        init(args.state_db)
        ids = pending(args.state_db, args.inbox, time.time(), args.limit)
        result = {'version': 11, 'mode': 'MANUAL', 'downloads_enabled': False,
                  'lookup_new': args.lookup_new, 'apply_series': args.apply_series,
                  'inbox_modified': False, 'notifications_sent': False, 'items': []}
        for nid in ids:
            try:
                item = process_one(nid, args)
            except RateLimited as exc:
                item = {'notification_id': nid, 'action': 'RATE_LIMITED_RETRY',
                        'retry_after_seconds': round(exc.wait_seconds, 1), 'eligible_for_acquisition': False}
            except Exception as exc:
                item = {'notification_id': nid, 'action': 'ERROR_RETRY_NO_STATUS_CHANGE',
                        'error_type': type(exc).__name__, 'eligible_for_acquisition': False}
            item['eligible_for_acquisition'] = False
            result['items'].append(item)
            record(args.state_db, nid, item['action'], time.time())
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
        print(json.dumps({'processed': len(result['items']), 'actions': [x['action'] for x in result['items']]}))

if __name__ == '__main__':
    main()
