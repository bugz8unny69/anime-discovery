"""V14 one-shot confidence evaluation from fresh identity evidence; no episode approval."""
import argparse
import fcntl
import json
import sqlite3
import time
from pathlib import Path
from anime_http_guard_v11 import protected, RateLimited
from anime_identity_worker_v10 import DATA, init
from anime_identity_worker_v12 import pending, record_v12
from anime_identity_worker_v11 import network_runner
from anime_identity_decision_v7 import decide
from anime_identity_persistence_v8 import persist
from anime_identity_worker_v9 import saved_readonly
from anime_identity_confidence_v14 import load_policy, score

def init_scores(path):
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS confidence_shadow_v14 (
            notification_id INTEGER PRIMARY KEY, evaluated_at REAL NOT NULL,
            policy_version TEXT NOT NULL, score INTEGER, decision TEXT NOT NULL,
            evidence_json TEXT NOT NULL)''')

def store_score(path, nid, result):
    with sqlite3.connect(path) as c:
        c.execute('''INSERT INTO confidence_shadow_v14 VALUES (?,?,?,?,?,?)
                     ON CONFLICT(notification_id) DO UPDATE SET evaluated_at=excluded.evaluated_at,
                     policy_version=excluded.policy_version, score=excluded.score,
                     decision=excluded.decision, evidence_json=excluded.evidence_json''',
                  (nid, time.time(), result['policy_version'], result['score_points'], result['decision'], json.dumps(result)))

def run(args):
    policy = load_policy(args.policy)
    init(args.state_db)
    init_scores(args.shadow_db)
    ids = pending(args.state_db, args.inbox, time.time(), args.limit)
    result = {'version': 14, 'mode': 'SHADOW', 'downloads_enabled': False,
              'episode_approvals_written': False, 'items': []}
    for nid in ids:
        try:
            saved = saved_readonly(args.verified, nid)
            if saved:
                item = {'notification_id': nid, 'action': 'SERIES_ALREADY_PERSISTED_EPISODE_PENDING',
                        'note': 'No fresh episode evidence; confidence not inferred from stored series alone'}
            else:
                with protected(args.rate_state, args.interval) as guard:
                    report = network_runner(nid)
                    decision = decide(report)
                    shadow = score(report, policy)
                    store_score(args.shadow_db, nid, shadow)
                    item = {'notification_id': nid, 'action': 'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE',
                            'shadow': shadow, 'http_requests': guard.count}
                    if decision['series_identity_verified'] and decision.get('tvdb_episode_exists'):
                        saved_result = persist(args.verified, decision, apply=True)
                        item['action'] = saved_result['action']
        except RateLimited as exc:
            item = {'notification_id': nid, 'action': 'RATE_LIMITED_RETRY', 'retry_after_seconds': exc.wait_seconds}
        except Exception as exc:
            item = {'notification_id': nid, 'action': 'ERROR_RETRY_NO_STATUS_CHANGE', 'error_type': type(exc).__name__}
        item['eligible_for_acquisition'] = False
        item['queue'] = record_v12(args.state_db, nid, item, time.time())
        result['items'].append(item)
    return result

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inbox', type=Path, default=DATA/'inbox.db')
    p.add_argument('--verified', type=Path, default=DATA/'verified-series.db')
    p.add_argument('--state-db', type=Path, default=DATA/'identity-queue-v10.db')
    p.add_argument('--rate-state', type=Path, default=DATA/'identity-http-v11.json')
    p.add_argument('--shadow-db', type=Path, default=DATA/'identity-confidence-v14.db')
    p.add_argument('--policy', type=Path, default=Path('/etc/anime-discovery/confidence-v14.json'))
    p.add_argument('--interval', type=float, default=2.0)
    p.add_argument('--limit', type=int, default=5)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    if not 2 <= args.interval <= 3600 or not 1 <= args.limit <= 10:
        p.error('Invalid interval or limit')
    with open(args.state_db.with_suffix('.lock'), 'a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print('V12 service holds queue lock; V14 skipped safely', flush=True)
            return 3
        report = run(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'processed': len(report['items']), 'actions': [x['action'] for x in report['items']]}))
    return 0
if __name__ == '__main__':
    raise SystemExit(main())
