#!/usr/bin/env python3
"""Conservative inbox triage. No network, torrent, download or identity approval actions."""
import argparse
import json
import re
import sqlite3
import time
from pathlib import Path
from anime_config_runtime import data_path

EPISODE = re.compile(r'(?<!\d)(?:\b(?:ep(?:isode)?)[ ._-]*|[ ._-]+-[ ._-]*)(\d{1,3})(?!\d)', re.I)

def classify(name):
    match = EPISODE.search(name)
    return ('IDENTITY_UNVERIFIED; EPISODE_CANDIDATE=' + match.group(1)) if match else 'IDENTITY_UNVERIFIED; EPISODE_NUMBER_AMBIGUOUS'

def run(db_path, *, dry_run=True, limit=100):
    if limit < 1 or limit > 2000:
        raise ValueError('limit out of range')
    path = Path(db_path)
    if not path.is_file() or path.is_symlink():
        raise ValueError('Existing regular inbox database required')
    # Require matching current hash before considering legacy decisions/mappings.
    data_dir = path.parent
    decisions_path = data_dir / 'review-resolutions.json'
    mappings_path = data_dir / 'identity-mappings.json'
    def load_json(p):
        try:
            v = json.loads(p.read_text())
        except FileNotFoundError:
            return {}
        if not isinstance(v, dict):
            raise ValueError(f'Invalid state file: {p.name}')
        return v
    decisions = load_json(decisions_path)
    mappings = load_json(mappings_path)
    uri = f'file:{path}?mode=ro' if dry_run else str(path)
    with sqlite3.connect(uri, uri=dry_run, timeout=5) as db:
        db.row_factory = sqlite3.Row
        if not dry_run:
            db.execute('PRAGMA busy_timeout=5000')
            db.execute('CREATE TABLE IF NOT EXISTS discovery_review_evidence (notification_id INTEGER PRIMARY KEY, info_hash TEXT NOT NULL, reason TEXT NOT NULL, checked_at INTEGER NOT NULL, usable_for_automation INTEGER NOT NULL DEFAULT 0 CHECK (usable_for_automation=0))')
        rows = db.execute('SELECT id,release_name,info_hash,status FROM notifications WHERE status=? ORDER BY id LIMIT ?', ('UNTRUSTED',limit)).fetchall()
        report=[]
        for row in rows:
            rid=str(row['id'])
            # Old inbox resets may reuse IDs. Never reinterpret an old mapping or resolution.
            if rid in decisions or rid in mappings:
                report.append({'id':row['id'],'result':'BLOCKED_STALE_OR_EXISTING_REVIEW_STATE'})
                continue
            reason=classify(row['release_name'])
            if not dry_run:
                with db:
                    db.execute('INSERT INTO discovery_review_evidence(notification_id,info_hash,reason,checked_at,usable_for_automation) VALUES(?,?,?,?,0) ON CONFLICT(notification_id) DO UPDATE SET info_hash=excluded.info_hash,reason=excluded.reason,checked_at=excluded.checked_at,usable_for_automation=0', (row['id'],row['info_hash'],reason,int(time.time())))
                    db.execute('UPDATE notifications SET status=? WHERE id=? AND info_hash=? AND status=?', ('NEEDS_REVIEW',row['id'],row['info_hash'],'UNTRUSTED'))
            report.append({'id':row['id'],'result':'WOULD_NEED_REVIEW' if dry_run else 'NEEDS_REVIEW','reason':reason})
    return report

if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--apply', action='store_true', help='Write NEEDS_REVIEW status and evidence; default is dry-run')
    p.add_argument('--limit', type=int, default=100)
    args=p.parse_args()
    print(json.dumps(run(data_path('inbox.db'),dry_run=not args.apply,limit=args.limit),indent=2))
