#!/usr/bin/env python3
"""Batch 3: persistent candidate triage, series readiness, and safe inventory planning.
No torrent, Sonarr, or media writes. Candidate titles never constitute verification.
"""
import argparse, json, re, sqlite3
from pathlib import Path

JOBS='/var/lib/anime-discovery/series-jobs.db'
BLOCK='EPISODE_ORDERING_MAPPING_NOT_CONFIRMED'

def triage_title(title, series, season, episode):
    """Conservative title screening only; never approves a release."""
    if not title or not series: return 'REVIEW_TITLE'
    norm=lambda s: re.sub(r'[^a-z0-9]+',' ',s.lower()).strip()
    name=norm(series)
    release=norm(title)
    if not re.search(r'(?<!\w)'+re.escape(name)+r'(?!\w)',release): return 'REJECT_TITLE_MISMATCH'
    if re.search(r'\b(batch|complete|season pack)\b',release): return 'REVIEW_MULTI_EPISODE'
    matches=set()
    for s,e in re.findall(r'(?i)\bS(\d{1,2})\s*E(\d{1,3})\b',title): matches.add((int(s),int(e)))
    if len(matches)>1: return 'REVIEW_MULTI_EPISODE'
    if matches and (season,episode) not in matches: return 'REJECT_EPISODE_MISMATCH'
    if not matches: return 'REVIEW_EPISODE_UNPROVEN'
    return 'CANDIDATE_NEEDS_INDEPENDENT_VERIFICATION'

def init(db):
    db.execute('''CREATE TABLE IF NOT EXISTS candidate_triage (
        tvdb_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
        candidate_key TEXT NOT NULL, triage_state TEXT NOT NULL,
        reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(tvdb_id,season,episode,candidate_key))''')

def process(db_path, catalog_path, *, write=False):
    catalog=json.loads(Path(catalog_path).read_text())
    if not isinstance(catalog,dict): raise ValueError('catalog must be an object')
    with sqlite3.connect(db_path) as db:
        db.execute('PRAGMA busy_timeout=15000')
        if write: init(db)
        jobs=db.execute('SELECT tvdb_id,season,episode,state FROM episode_jobs ORDER BY tvdb_id,season,episode').fetchall()
        results=[]
        for tvdb,season,episode,state in jobs:
            title=catalog.get(str(tvdb))
            if not title:
                results.append(dict(tvdb_id=tvdb,season=season,episode=episode,job_state=state,readiness='MISSING_TRUSTED_SERIES_TITLE',candidates={}))
                continue
            rows=db.execute('SELECT candidate_key,title FROM historical_candidates WHERE tvdb_id=? AND season=? AND episode=?',(tvdb,season,episode)).fetchall() if table_exists(db,'historical_candidates') else []
            counts={}; decisions=[]
            for key,release in rows:
                decision=triage_title(release,title,season,episode)
                counts[decision]=counts.get(decision,0)+1
                if write: decisions.append((tvdb,season,episode,key,decision))
            if write and decisions:
                with db:
                    db.executemany('''INSERT INTO candidate_triage(tvdb_id,season,episode,candidate_key,triage_state)
                    VALUES(?,?,?,?,?) ON CONFLICT(tvdb_id,season,episode,candidate_key)
                    DO UPDATE SET triage_state=excluded.triage_state,reviewed_at=CURRENT_TIMESTAMP''',decisions)
            readiness=('BLOCKED_VERIFICATION' if state=='BLOCKED_VERIFICATION' else
                       'SEARCH_REQUIRED' if state=='SEARCH_REQUIRED' and not rows else
                       'CANDIDATES_UNTRUSTED' if state=='SEARCH_REQUIRED' else
                       'REQUIRES_STAGING_AND_OWNERSHIP_CHECK' if state=='VERIFIED_CANDIDATE' else
                       'NOT_READY_FOR_KEEP')
            results.append(dict(tvdb_id=tvdb,season=season,episode=episode,job_state=state,readiness=readiness,candidates=counts))
        grouped={}
        for r in results:
            k=(r['tvdb_id'],r['season']); grouped.setdefault(k,[]).append(r)
        return {'write_scope':'candidate_triage table only' if write else 'none',
                'episodes':results,
                'series':[{'tvdb_id':tvdb,'season':season,'keep_ready':False,
                           'reason':'No trusted per-episode staging and Sonarr import readiness evidence; fail closed',
                           'episode_count':len(items)} for (tvdb,season),items in grouped.items()]}

def table_exists(db,name):
    return bool(db.execute('SELECT 1 FROM sqlite_master WHERE type="table" AND name=?',(name,)).fetchone())

def main():
    p=argparse.ArgumentParser();p.add_argument('--jobs',default=JOBS);p.add_argument('--catalog',default='/etc/anime-discovery/search-catalog.json');p.add_argument('--persist-triage',action='store_true');a=p.parse_args()
    print(json.dumps(process(a.jobs,a.catalog,write=a.persist_triage),indent=2))
if __name__=='__main__':main()

def acquisition_decision(*, verified, blockers, rejected, info_hash, existing_hashes, owned_canonical, legacy_owned):
    """Pure decision function; never authorizes an external write on its own."""
    if rejected: return 'REPLAY_BLOCKED_REJECTED'
    if not verified or blockers: return 'BLOCKED_VERIFICATION'
    if owned_canonical: return 'ALREADY_STAGED'
    if legacy_owned: return 'OWNED_LEGACY_REQUIRES_SAFE_MIGRATION'
    if not info_hash or not re.fullmatch(r'[0-9a-fA-F]{40}',info_hash): return 'BLOCKED_NO_VALID_TORRENT_HASH'
    if info_hash.lower() in {h.lower() for h in existing_hashes}: return 'REUSE_EXISTING_TORRENT'
    return 'ELIGIBLE_FOR_LOCKED_PAUSED_ADD_AFTER_PERSISTED_APPROVAL'
