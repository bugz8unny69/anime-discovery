#!/usr/bin/env python3
"""Persistent, fail-closed series backlog planner. No network or media writes.

Consumes ONLY authoritative inbox + V16 persisted verification. A proposed
mapping may create a blocked planning row but never authorize acquisition.
"""
import argparse
import json
import sqlite3
import time
from pathlib import Path

DEFAULT_INBOX = '/var/lib/anime-discovery/inbox.db'
DEFAULT_VERIFY = '/var/lib/anime-discovery/identity-confidence-v15.db'
DEFAULT_JOBS = '/var/lib/anime-discovery/series-jobs.db'
BLOCKER = 'EPISODE_ORDERING_MAPPING_NOT_CONFIRMED'


def connect(path):
    return sqlite3.connect(f'file:{Path(path).resolve()}?mode=ro', uri=True)


def init(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS series_jobs (
        tvdb_id INTEGER NOT NULL, season INTEGER NOT NULL,
        latest_observed INTEGER NOT NULL, updated_at INTEGER NOT NULL,
        PRIMARY KEY(tvdb_id,season));
      CREATE TABLE IF NOT EXISTS episode_jobs (
        tvdb_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
        state TEXT NOT NULL, notification_id INTEGER, info_hash TEXT,
        blockers_json TEXT NOT NULL DEFAULT '[]', updated_at INTEGER NOT NULL,
        PRIMARY KEY(tvdb_id,season,episode));
      CREATE TABLE IF NOT EXISTS job_events (
        id INTEGER PRIMARY KEY, notification_id INTEGER NOT NULL UNIQUE,
        tvdb_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
        state TEXT NOT NULL, created_at INTEGER NOT NULL);
    ''')


def reconcile(inbox, verify, jobs):
    now = int(time.time())
    with connect(inbox) as src, connect(verify) as evidence, sqlite3.connect(jobs, timeout=15) as db:
        db.execute('PRAGMA busy_timeout=15000')
        db.execute('BEGIN IMMEDIATE')
        init(db)
        rows = src.execute('SELECT id,info_hash FROM notifications ORDER BY id').fetchall()
        processed = 0
        for nid, info_hash in rows:
            ver = evidence.execute('SELECT verified,evidence_json FROM episode_verification_v16 WHERE notification_id=?', (nid,)).fetchone()
            if not ver:
                continue
            try:
                payload = json.loads(ver[1]); mapping = payload.get('proposed_mapping') or {}
                tvdb = int(mapping['tvdb_id']); season = int(mapping['tvdb_season']); ep = int(mapping['tvdb_episode'])
                if tvdb <= 0 or season < 0 or ep < 1 or ep > 10000:
                    continue
                blockers = payload.get('blockers') or []
                approved = bool(ver[0]) and payload.get('episode_identity_verified') is True and not blockers
                state = 'VERIFIED_CANDIDATE' if approved else 'BLOCKED_VERIFICATION'
            except (ValueError, TypeError, KeyError, AttributeError, json.JSONDecodeError):
                continue
            prior = db.execute('SELECT 1 FROM job_events WHERE notification_id=?', (nid,)).fetchone()
            if prior:
                continue
            db.execute('INSERT INTO series_jobs VALUES(?,?,?,?) ON CONFLICT(tvdb_id,season) DO UPDATE SET latest_observed=max(latest_observed,excluded.latest_observed),updated_at=excluded.updated_at', (tvdb,season,ep,now))
            db.execute('INSERT INTO episode_jobs(tvdb_id,season,episode,state,notification_id,info_hash,blockers_json,updated_at) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(tvdb_id,season,episode) DO UPDATE SET state=excluded.state,notification_id=excluded.notification_id,info_hash=excluded.info_hash,blockers_json=excluded.blockers_json,updated_at=excluded.updated_at WHERE episode_jobs.state="SEARCH_REQUIRED"', (tvdb,season,ep,state,nid,info_hash,json.dumps(blockers),now))
            db.execute('INSERT INTO job_events(notification_id,tvdb_id,season,episode,state,created_at) VALUES(?,?,?,?,?,?)', (nid,tvdb,season,ep,state,now))
            processed += 1
        # Create missing earlier episode placeholders; never invent releases or approve downloads.
        for tvdb, season, latest in db.execute('SELECT tvdb_id,season,latest_observed FROM series_jobs').fetchall():
            for ep in range(1, latest + 1):
                db.execute('INSERT OR IGNORE INTO episode_jobs(tvdb_id,season,episode,state,updated_at) VALUES(?,?,?,?,?)', (tvdb,season,ep,'SEARCH_REQUIRED',now))
        db.commit()
        return {'new_notifications_planned':processed,'series':db.execute('SELECT count(*) FROM series_jobs').fetchone()[0], 'search_required':db.execute("SELECT count(*) FROM episode_jobs WHERE state='SEARCH_REQUIRED'").fetchone()[0], 'blocked':db.execute("SELECT count(*) FROM episode_jobs WHERE state='BLOCKED_VERIFICATION'").fetchone()[0], 'verified_candidates':db.execute("SELECT count(*) FROM episode_jobs WHERE state='VERIFIED_CANDIDATE'").fetchone()[0], 'writes':'series-jobs.db only; no network, torrents, or media'}


def main():
    p=argparse.ArgumentParser(); p.add_argument('--inbox',default=DEFAULT_INBOX); p.add_argument('--verification',default=DEFAULT_VERIFY); p.add_argument('--jobs',default=DEFAULT_JOBS); a=p.parse_args()
    print(json.dumps(reconcile(a.inbox,a.verification,a.jobs),indent=2))
if __name__=='__main__': main()
