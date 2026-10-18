#!/usr/bin/env python3
"""Read-only Prowlarr search consumer for persistent episode jobs.

Candidates are UNTRUSTED until the existing identity worker independently verifies
release identity and AniDB/TVDB episode ordering. No qB or Sonarr writes.
"""
import argparse
import json
import sqlite3
import urllib.parse
import urllib.request
from pathlib import Path
from anime_config_runtime import get

JOBS = '/var/lib/anime-discovery/series-jobs.db'
CATALOG = '/etc/anime-discovery/search-catalog.json'


def search(api_url, api_key, query, *, opener=urllib.request.urlopen):
    base = api_url.rstrip('/')
    parsed = urllib.parse.urlsplit(base)
    if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError('Invalid Prowlarr base URL')
    url = base + '/api/v1/search?' + urllib.parse.urlencode({'query': query, 'type': 'search'})
    req = urllib.request.Request(url, headers={'X-Api-Key': api_key, 'Accept': 'application/json'})
    with opener(req, timeout=15) as response:
        data = json.load(response)
    if not isinstance(data, list):
        raise ValueError('Unexpected Prowlarr response')
    return data


def init(db):
    db.executescript('''
      CREATE TABLE IF NOT EXISTS historical_search_attempts (
        tvdb_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
        query TEXT NOT NULL, status TEXT NOT NULL, error TEXT,
        searched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        PRIMARY KEY(tvdb_id,season,episode,query));
      CREATE TABLE IF NOT EXISTS historical_candidates (
        tvdb_id INTEGER NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
        candidate_key TEXT NOT NULL, title TEXT NOT NULL, guid TEXT,
        download_url TEXT, info_hash TEXT, indexer_id INTEGER,
        trust_state TEXT NOT NULL DEFAULT 'UNTRUSTED',
        PRIMARY KEY(tvdb_id,season,episode,candidate_key));
    ''')


def process(jobs, api_url, api_key, *, max_jobs=20, catalog_path=CATALOG, opener=urllib.request.urlopen):
    if not api_key:
        raise ValueError('Prowlarr API key is not configured')
    with sqlite3.connect(jobs, timeout=15) as db:
        db.execute('PRAGMA busy_timeout=15000')
        init(db)
        rows = db.execute('''SELECT j.tvdb_id,j.season,j.episode
          FROM episode_jobs j WHERE j.state='SEARCH_REQUIRED'
          ORDER BY j.tvdb_id,j.season,j.episode LIMIT ?''', (max_jobs,)).fetchall()
        # TVDB ID alone isn't a searchable title; require a trusted catalog mapping.
        catalog = Path(catalog_path)
        titles = json.loads(catalog.read_text()) if catalog.is_file() else {}
        if not isinstance(titles, dict):
            raise ValueError('Trusted series catalog must be a JSON object')
        results = []
        for tvdb, season, episode in rows:
            title = titles.get(str(tvdb))
            if not isinstance(title, str) or not title.strip():
                results.append({'tvdb_id':tvdb,'season':season,'episode':episode,'status':'MISSING_TRUSTED_SERIES_TITLE'})
                continue
            query = f'{title} S{season:02d}E{episode:02d}'
            prior = db.execute('SELECT status FROM historical_search_attempts WHERE tvdb_id=? AND season=? AND episode=? AND query=?', (tvdb,season,episode,query)).fetchone()
            if prior and prior[0] == 'SEARCHED':
                results.append({'tvdb_id':tvdb,'season':season,'episode':episode,'status':'ALREADY_SEARCHED'})
                continue
            try:
                candidates = search(api_url, api_key, query, opener=opener)
                # Commit all candidates and the search marker together.
                with db:
                    for item in candidates:
                        if not isinstance(item,dict): continue
                        title_value = item.get('title')
                        guid = item.get('guid')
                        if not isinstance(title_value,str) or not title_value.strip(): continue
                        key = str(guid or item.get('downloadUrl') or '')
                        if not key: continue
                        db.execute('''INSERT OR IGNORE INTO historical_candidates
                          (tvdb_id,season,episode,candidate_key,title,guid,download_url,info_hash,indexer_id)
                          VALUES(?,?,?,?,?,?,?,?,?)''', (tvdb,season,episode,key,title_value,str(guid) if guid else None,
                          item.get('downloadUrl'),item.get('infoHash'),item.get('indexerId')))
                    db.execute('''INSERT INTO historical_search_attempts(tvdb_id,season,episode,query,status,error)
                      VALUES(?,?,?,?,?,NULL) ON CONFLICT(tvdb_id,season,episode,query)
                      DO UPDATE SET status=excluded.status,error=NULL,searched_at=CURRENT_TIMESTAMP''',
                      (tvdb,season,episode,query,'SEARCHED'))
                results.append({'tvdb_id':tvdb,'season':season,'episode':episode,'status':'SEARCHED','returned':len(candidates)})
            except (OSError, ValueError, json.JSONDecodeError) as exc:
                # Don't persist credentials or sensitive exception text.
                results.append({'tvdb_id':tvdb,'season':season,'episode':episode,'status':'SEARCH_ERROR','error_type':type(exc).__name__})
        return results


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--jobs',default=JOBS)
    p.add_argument('--max-jobs',type=int,default=20)
    args=p.parse_args()
    url = get('prowlarr.url')
    api_key = get('prowlarr.api_key')
    if not url or not api_key: p.error('Configure prowlarr.url and prowlarr.api_key using anime_discovery.py')
    print(json.dumps(process(args.jobs,url,api_key,max_jobs=args.max_jobs),indent=2))
if __name__ == '__main__': main()
