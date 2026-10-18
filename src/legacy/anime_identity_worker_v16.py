#!/usr/bin/env python3
"""V16 verification watch: automatically evaluates, never approves or downloads."""
import json
import sqlite3
import time
from anime_identity_worker_v15 import *
from anime_identity_worker_v15 import main as v15_main
from anime_episode_verification_v16 import verify


def init_verifications(path):
    with sqlite3.connect(path) as c:
        c.execute('''CREATE TABLE IF NOT EXISTS episode_verification_v16 (
            notification_id INTEGER PRIMARY KEY, evaluated_at REAL NOT NULL,
            decision TEXT NOT NULL, verified INTEGER NOT NULL,
            evidence_json TEXT NOT NULL)''')


def store_verification(path, nid, result):
    with sqlite3.connect(path, timeout=15) as c:
        c.execute('''INSERT INTO episode_verification_v16 VALUES (?,?,?,?,?)
            ON CONFLICT(notification_id) DO UPDATE SET evaluated_at=excluded.evaluated_at,
            decision=excluded.decision, verified=excluded.verified,
            evidence_json=excluded.evidence_json''',
            (nid, time.time(), result['decision'], int(result['episode_identity_verified']),
             json.dumps(result, ensure_ascii=False)))


def process_one(nid, args, policy):
    saved = saved_readonly(args.verified, nid)
    if saved and (saved[3] or saved[4]):
        raise ValueError('Stored identity unexpectedly authorizes acquisition')
    with protected(args.rate_state, args.interval) as guard:
        report = network_runner(nid)
        shadow = score(report, policy)
        verification = verify(report, shadow)
        store_score(args.shadow_db, nid, shadow)
        store_verification(args.shadow_db, nid, verification)
        item = {'notification_id': nid, 'action': verification['decision'],
                'shadow_score': shadow['score_points'], 'shadow_decision': shadow['decision'],
                'verification_blockers': verification['blockers'],
                'episode_identity_verified': verification['episode_identity_verified'],
                'proposed_mapping': verification['proposed_mapping'],
                'http_requests': guard.count}
        if not saved:
            decision = decide(report)
            if decision['series_identity_verified'] and decision.get('tvdb_episode_exists'):
                persisted = persist(args.verified, decision, apply=True)
                item['series_persistence_action'] = persisted['action']
        return item


def pending_verification_reconcile(state_db, inbox, now, limit, shadow_db):
    """Select fresh work plus DONE series rows missing V16 verification evidence.

    Never retry a row with an existing V16 verification record here; evidence
    refresh requires a separate deliberate policy. Preserve V12 retry pacing.
    """
    from anime_identity_worker_v12 import pending as original_pending, DONE
    from anime_identity_worker_v9 import rows_readonly
    selected = list(original_pending(state_db, inbox, now, limit))
    if len(selected) >= limit:
        return selected
    with sqlite3.connect(state_db, timeout=15) as state, sqlite3.connect(shadow_db, timeout=15) as shadow:
        for nid, status in sorted(rows_readonly(inbox, 100)):
            if len(selected) >= limit:
                break
            if status != 'UNTRUSTED' or nid in selected:
                continue
            prior = state.execute('SELECT last_action FROM identity_queue WHERE notification_id=?', (nid,)).fetchone()
            if not prior or prior[0] not in DONE:
                continue
            verified = shadow.execute('SELECT 1 FROM episode_verification_v16 WHERE notification_id=?', (nid,)).fetchone()
            if not verified:
                selected.append(nid)
    return selected


def main(argv=None):
    # Reuse V15's lock, queue handling, pacing, CLI and service loop.
    import anime_identity_worker_v15 as worker
    old_process = worker.process_one
    old_init = worker.init_scores
    old_pending = worker.pending
    def init_both(path):
        old_init(path)
        init_verifications(path)
    worker.process_one = process_one
    worker.init_scores = init_both
    old_batch = worker.process_batch
    def batch_with_reconcile(args, policy):
        worker.pending = lambda state_db, inbox, now, limit: pending_verification_reconcile(
            state_db, inbox, now, limit, args.shadow_db)
        return old_batch(args, policy)
    worker.process_batch = batch_with_reconcile
    try:
        return v15_main(argv)
    finally:
        worker.process_one = old_process
        worker.init_scores = old_init
        worker.pending = old_pending
        worker.process_batch = old_batch

if __name__ == '__main__':
    raise SystemExit(main())
