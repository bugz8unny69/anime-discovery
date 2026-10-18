#!/usr/bin/env python3
"""Read-only AniDB/TVDB discovery candidate probe. Never changes inbox or identity state."""
import argparse
import gzip
import io
import json
import re
import sqlite3
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from anime_config_runtime import data_path, get
from anime_identity_verify import TITLES_URL, TVDB_URL, tvdb_token, request_json

EP = re.compile(r'\s+-\s+(\d{1,3})(?!\d)|\b(?:ep|episode)[ ._-]*(\d{1,3})\b', re.I)
PREFIX = re.compile(r'^\s*(?:\[[^]]+\]\s*)+')
TRAIL = re.compile(r'\s*(?:\[[^]]+\]\s*)+$')

def release_title(raw):
    value = PREFIX.sub('', raw).strip()
    m = EP.search(value)
    episode = next((int(x) for x in m.groups() if x), None) if m else None
    title = value[:m.start()].strip() if m else TRAIL.sub('', value).strip()
    title = re.sub(r'\s*\([^)]*(?:dual[ -]?audio|multi[ -]?audio)[^)]*\)', '', title, flags=re.I).strip()
    aliases = [title]
    for part in re.findall(r'\(([^()]*)\)', title):
        if part and not re.search(r'\b(?:dual|audio|1080p|720p|dub|sub)\b', part, re.I):
            aliases.append(part.strip())
    aliases.append(re.sub(r'\s*\([^()]*\)', '', title).strip())
    return list(dict.fromkeys(x for x in aliases if x)), episode

def norm(s):
    return re.sub(r'[^a-z0-9]+', '', s.casefold())

def load_anidb(path):
    content = path.read_bytes()
    stream = gzip.GzipFile(fileobj=io.BytesIO(content)) if content[:2] == b'\x1f\x8b' else io.BytesIO(content)
    for _, node in ET.iterparse(stream, events=('end',)):
        if node.tag == 'anime':
            aid = node.attrib.get('aid')
            titles = [t.text.strip() for t in node.findall('title') if t.text and t.text.strip()]
            if aid and titles:
                yield aid, titles
            node.clear()

def anidb_matches(path, aliases, limit=10):
    wanted = {norm(a) for a in aliases if norm(a)}
    matches = []
    for aid, titles in load_anidb(path):
        exact = [t for t in titles if norm(t) in wanted]
        if exact:
            matches.append({'anidb_id': aid, 'matched_titles': exact[:5], 'titles': titles[:12]})
            if len(matches) > limit:
                break
    return matches, len(matches) > limit

def tvdb_candidates(aliases, api_key):
    token = tvdb_token(api_key)
    results = {}
    errors = []
    for alias in aliases[:3]:
        url = TVDB_URL + '/search?' + urllib.parse.urlencode({'query': alias, 'type': 'series'})
        try:
            response = request_json(url, bearer=token)
            for record in (response.get('data') or [])[:15]:
                ident = record.get('tvdb_id') or record.get('id')
                if not ident:
                    continue
                key = str(ident)
                names = [record.get('name') or '', record.get('name_translated') or '', record.get('original_name') or '']
                names += [x for x in (record.get('aliases') or []) if isinstance(x, str)]
                results[key] = {'tvdb_id': key, 'name': record.get('name'), 'matched_query': alias,
                                'exact_title_overlap': bool({norm(n) for n in names if n} & {norm(a) for a in aliases})}
        except Exception as exc:
            errors.append(f'TVDB search failed for {alias!r}: {type(exc).__name__}')
    return list(results.values()), errors

def probe(notification_id, cache, refresh=False):
    db_path = data_path('inbox.db')
    with sqlite3.connect(f'file:{db_path}?mode=ro', uri=True) as conn:
        row = conn.execute('SELECT id,release_name,status FROM notifications WHERE id=?', (notification_id,)).fetchone()
    if not row:
        raise ValueError('Notification not found')
    aliases, episode = release_title(row[1])
    report = {'notification_id': row[0], 'status_unchanged': row[2], 'release_name': row[1],
              'title_candidates': aliases, 'episode_candidate': episode,
              'verified_identity': False, 'usable_for_automation': False, 'anidb_candidates': [], 'tvdb_candidates': [], 'issues': []}
    if refresh:
        req = urllib.request.Request(TITLES_URL, headers={'User-Agent': 'AnimeDiscoveryCandidateProbe/1.0'})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read(32*1024*1024+1)
        if len(data) > 32*1024*1024:
            raise ValueError('AniDB index exceeds maximum download size')
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
    if cache.exists():
        report['anidb_candidates'], truncated = anidb_matches(cache, aliases)
        if truncated:
            report['issues'].append('More than ten AniDB exact-title matches; results truncated')
    else:
        report['issues'].append('AniDB title cache missing; use --refresh-titles')
    key = get('tvdb.api_key') if get('tvdb.enabled') else None
    if key:
        try:
            report['tvdb_candidates'], errors = tvdb_candidates(aliases, key)
            report['issues'].extend(errors)
        except Exception as exc:
            report['issues'].append(f'TVDB authentication unavailable: {type(exc).__name__}')
    else:
        report['issues'].append('TVDB unavailable or disabled')
    report['next_action'] = 'INSPECT_CANDIDATES; NO_STATUS_CHANGE'
    return report

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--notification-id', type=int, default=1)
    p.add_argument('--titles-cache', type=Path, default=None)
    p.add_argument('--refresh-titles', action='store_true')
    args = p.parse_args()
    print(json.dumps(probe(args.notification_id, args.titles_cache or data_path('anidb-titles.xml.gz'), args.refresh_titles), indent=2, ensure_ascii=False))
