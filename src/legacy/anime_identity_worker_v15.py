#!/usr/bin/env python3
"""V15 background identity worker with fresh-evidence shadow scoring; never approves episodes."""
import argparse
import fcntl
import json
import os
import sqlite3
import time
from pathlib import Path
from anime_identity_worker_v10 import DATA, init
from anime_identity_worker_v12 import pending, record_v12
from anime_identity_worker_v9 import saved_readonly
from anime_identity_worker_v11 import network_runner
from anime_http_guard_v11 import protected, RateLimited
from anime_identity_decision_v7 import decide
from anime_identity_persistence_v8 import persist
from anime_identity_confidence_v14 import load_policy, score

DONE = {'SERIES_ALREADY_PERSISTED_EPISODE_PENDING', 'INSERTED', 'UNCHANGED', 'EVIDENCE_UPDATED'}

def init_scores(path):
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS confidence_shadow_v15 (
          notification_id INTEGER PRIMARY KEY, evaluated_at REAL NOT NULL,
          policy_version TEXT NOT NULL, score INTEGER NOT NULL, decision TEXT NOT NULL,
          evidence_json TEXT NOT NULL)''')

def store_score(path, nid, shadow):
    with sqlite3.connect(path, timeout=15) as c:
        c.execute('''INSERT INTO confidence_shadow_v15 VALUES (?,?,?,?,?,?)
        ON CONFLICT(notification_id) DO UPDATE SET evaluated_at=excluded.evaluated_at,
        policy_version=excluded.policy_version, score=excluded.score,
        decision=excluded.decision, evidence_json=excluded.evidence_json''',
        (nid, time.time(), shadow['policy_version'], shadow['score_points'],
         shadow['decision'], json.dumps(shadow, ensure_ascii=False)))

def process_one(nid, args, policy):
    saved = saved_readonly(args.verified, nid)
    if saved:
        if saved[3] or saved[4]:
            raise ValueError('Stored identity unexpectedly authorizes acquisition')
        # Series reuse does not prove episode identity. Gather fresh episode evidence
        # for this notification, under the same HTTP guard, before scoring.
        with protected(args.rate_state, args.interval) as guard:
            report = network_runner(nid)
            shadow = score(report, policy)
            store_score(args.shadow_db, nid, shadow)
            return {'notification_id': nid, 'action': 'SERIES_ALREADY_PERSISTED_EPISODE_PENDING',
                    'anidb_id': saved[0], 'tvdb_id': saved[1],
                    'shadow_score': shadow['score_points'],
                    'shadow_decision': shadow['decision'],
                    'shadow_blockers': shadow['blockers'],
                    'http_requests': guard.count}
    with protected(args.rate_state, args.interval) as guard:
        report = network_runner(nid)
        decision = decide(report)
        shadow = score(report, policy)
        # Write the shadow decision even when series verification remains unresolved.
        store_score(args.shadow_db, nid, shadow)
        item = {'notification_id': nid, 'action': 'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE',
                'decision': decision['decision'], 'issues': decision.get('issues', []),
                'shadow_score': shadow['score_points'], 'shadow_decision': shadow['decision'],
                'shadow_blockers': shadow['blockers'], 'http_requests': guard.count}
        if decision['series_identity_verified'] and decision.get('tvdb_episode_exists'):
            result = persist(args.verified, decision, apply=True)
            item.update(action=result['action'], anidb_id=result['anidb_id'], tvdb_id=result['tvdb_id'])
        return item

def process_batch(args, policy):
    ids = pending(args.state_db, args.inbox, time.time(), args.limit)
    report = {'version': 15, 'mode': 'SHADOW_WATCH' if args.watch else 'SHADOW_MANUAL',
              'downloads_enabled': False, 'episode_approvals_written': False,
              'inbox_modified': False, 'notifications_sent': False, 'items': []}
    for nid in ids:
        try:
            item = process_one(nid, args, policy)
        except RateLimited as exc:
            item = {'notification_id': nid, 'action': 'RATE_LIMITED_RETRY',
                    'retry_after_seconds': exc.wait_seconds}
        except Exception as exc:
            item = {'notification_id': nid, 'action': 'ERROR_RETRY_NO_STATUS_CHANGE',
                    'error_type': type(exc).__name__}
        item['eligible_for_acquisition'] = False
        item['queue'] = record_v12(args.state_db, nid, item, time.time())
        report['items'].append(item)
    return report

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inbox', type=Path, default=DATA/'inbox.db')
    p.add_argument('--verified', type=Path, default=DATA/'verified-series.db')
    p.add_argument('--state-db', type=Path, default=DATA/'identity-queue-v10.db')
    p.add_argument('--rate-state', type=Path, default=DATA/'identity-http-v11.json')
    p.add_argument('--shadow-db', type=Path, default=DATA/'identity-confidence-v15.db')
    p.add_argument('--policy', type=Path, default=Path('/etc/anime-discovery/confidence-v14.json'))
    p.add_argument('--output', type=Path, required=True)
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true')
    mode.add_argument('--watch', action='store_true')
    p.add_argument('--interval', type=float, default=2.0)
    p.add_argument('--poll-seconds', type=float, default=2.0)
    p.add_argument('--limit', type=int, default=5)
    args = p.parse_args(argv)
    if not (2 <= args.interval <= 3600 and 1 <= args.poll_seconds <= 3600 and 1 <= args.limit <= 10):
        p.error('Invalid pacing/polling/limit')
    args.state_db.parent.mkdir(parents=True, exist_ok=True)
    with open(args.state_db.with_suffix('.lock'), 'a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('Another worker owns the shared queue lock; no work performed', flush=True)
            return 3
        init(args.state_db)
        init_scores(args.shadow_db)
        while True:
            policy = load_policy(args.policy)  # reload changes without service restart
            result = process_batch(args, policy)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            tmp = args.output.with_suffix('.tmp')
            tmp.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
            os.replace(tmp, args.output)
            print(json.dumps({'processed': len(result['items']),
                              'actions': [x['action'] for x in result['items']]}), flush=True)
            if args.once:
                return 0
            time.sleep(args.poll_seconds)

if __name__ == '__main__':
    raise SystemExit(main())
