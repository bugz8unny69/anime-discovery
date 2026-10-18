#!/usr/bin/env python3
"""Persist independently verified SERIES identities, never episode approvals.

No imports from live controller, no qBittorrent access, and no inbox writes.
"""
import argparse
import datetime as dt
import json
import os
import sqlite3
import sys
from pathlib import Path

SCHEMA = '''CREATE TABLE IF NOT EXISTS verified_series_identity (
  notification_id INTEGER PRIMARY KEY CHECK(notification_id > 0),
  anidb_id TEXT NOT NULL,
  tvdb_id TEXT NOT NULL,
  mapping_source TEXT NOT NULL,
  decision TEXT NOT NULL CHECK(decision = 'SERIES_VERIFIED_EPISODE_PENDING'),
  episode_identity_verified INTEGER NOT NULL DEFAULT 0 CHECK(episode_identity_verified = 0),
  eligible_for_acquisition INTEGER NOT NULL DEFAULT 0 CHECK(eligible_for_acquisition = 0),
  evidence_json TEXT NOT NULL,
  evidence_sha256 TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
)'''

def validate(record):
    if not isinstance(record, dict): raise ValueError('Expected JSON object')
    required = {'series_identity_verified': True, 'episode_identity_verified': False,
                'eligible_for_acquisition': False, 'write_performed': False,
                'status_unchanged': 'UNTRUSTED', 'decision': 'SERIES_VERIFIED_EPISODE_PENDING',
                'tvdb_episode_exists': True}
    for key, expected in required.items():
        if type(record.get(key)) is not type(expected) or record.get(key) != expected:
            raise ValueError(f'Unsafe or unexpected {key}: {record.get(key)!r}')
    n = record.get('notification_id')
    if type(n) is not int or n <= 0: raise ValueError('Invalid notification ID')
    series = record.get('series')
    if not isinstance(series, dict): raise ValueError('Missing series')
    for key in ('anidb_id', 'tvdb_id'):
        val = series.get(key)
        if not isinstance(val, str) or not val.isdigit() or int(val) <= 0:
            raise ValueError(f'Invalid {key}')
    source = series.get('mapping_source')
    if not isinstance(source, str) or not source.startswith('https://raw.githubusercontent.com/Anime-Lists/anime-lists/'):
        raise ValueError('Unrecognized mapping source')
    return n, series

def persist(db_path, record, apply=False):
    import hashlib
    n, series = validate(record)
    canonical = json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    digest = hashlib.sha256(canonical.encode()).hexdigest()
    result = {'notification_id': n, 'anidb_id': series['anidb_id'],
              'tvdb_id': series['tvdb_id'], 'evidence_sha256': digest,
              'episode_identity_verified': False, 'eligible_for_acquisition': False,
              'applied': False, 'action': 'DRY_RUN_VALIDATED'}
    if not apply: return result
    db = sqlite3.connect(str(db_path), timeout=10)
    try:
        db.execute('PRAGMA busy_timeout=10000')
        db.execute('BEGIN IMMEDIATE')
        db.execute(SCHEMA)
        existing = db.execute('SELECT anidb_id,tvdb_id,evidence_sha256 FROM verified_series_identity WHERE notification_id=?', (n,)).fetchone()
        if existing and existing[:2] != (series['anidb_id'], series['tvdb_id']):
            raise ValueError('IDENTITY_CONFLICT: existing mapping differs; no overwrite')
        now = dt.datetime.now(dt.timezone.utc).isoformat()
        if existing and existing[2] == digest:
            result['action'] = 'UNCHANGED'
        elif existing:
            db.execute('UPDATE verified_series_identity SET mapping_source=?, evidence_json=?, evidence_sha256=?, updated_at=? WHERE notification_id=?',
                       (series['mapping_source'], canonical, digest, now, n))
            result['action'] = 'EVIDENCE_UPDATED'
        else:
            db.execute('INSERT INTO verified_series_identity (notification_id,anidb_id,tvdb_id,mapping_source,decision,evidence_json,evidence_sha256,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?)',
                       (n, series['anidb_id'], series['tvdb_id'], series['mapping_source'], record['decision'], canonical, digest, now, now))
            result['action'] = 'INSERTED'
        db.commit()
        result['applied'] = True
        return result
    except Exception:
        db.rollback()
        raise
    finally: db.close()

def main():
    p=argparse.ArgumentParser()
    p.add_argument('--input', required=True)
    p.add_argument('--db', default='/var/lib/anime-discovery/verified-series.db')
    p.add_argument('--output', required=True)
    p.add_argument('--apply', action='store_true', help='Write ONLY to dedicated verified-series DB')
    args=p.parse_args()
    try:
        record=json.loads(Path(args.input).read_text(encoding='utf-8'))
        result=persist(args.db, record, args.apply)
        output=Path(args.output)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(result,indent=2))
    except Exception as exc:
        print(f'ERROR: {exc}',file=sys.stderr)
        return 1
    return 0
if __name__=='__main__': sys.exit(main())
