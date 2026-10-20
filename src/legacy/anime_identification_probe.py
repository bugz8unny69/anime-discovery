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
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path
from anime_config_runtime import data_path, get
from anime_identity_verify import TITLES_URL, TVDB_URL, tvdb_token, request_json

EP = re.compile(
    r'(?<![A-Za-z0-9])S(?P<season>\d{1,2})[ ._-]*E(?P<season_ep>\d{1,4})(?!\d)'
    r'|\s+-\s+(?P<dash_ep>\d{1,4})(?:v\d+)?(?!\d)'
    r'|\b(?:ep|episode)[ ._-]*(?P<word_ep>\d{1,4})\b', re.I)
PREFIX = re.compile(r'^\s*(?:\[[^]]+\]\s*)+')
SEASON_TOKEN = re.compile(r'(?<![A-Za-z0-9])S\d{1,2}(?![A-Za-z0-9])', re.I)
SEASON_WORD = re.compile(r'\bSeason[ ._-]*S?\d{1,2}\b', re.I)
RELEASE_TECH = re.compile(
    r'(?<![A-Za-z0-9])(?:\d{3,4}p|4K|UHD|WEB[ ._-]?DL|WEBRip|BluRay|'
    r'BDRip|BDMV|HEVC|AV1|x264|x265|H264|H265)(?![A-Za-z0-9])', re.I)
META_GROUP = re.compile(r'\(([^()]*)\)')
TRAIL = re.compile(r'\s*(?:\[[^]]+\]\s*)+$')
METADATA_ONLY = re.compile(
    r'^(?:Batch|Season[ ._-]*S?\d{1,2}|Complete(?:[ ._-]*Season)?|'
    r'Dual[ ._-]*Audio(?:,\s*Multi[ ._-]*Subs)?|'
    r'Multi[ ._-]*Subs|Multi[ ._-]*Audio|'
    r'\d{3,4}p|4K|AV1|HEVC|x26[45]|'
    r'BD|BDRip|WEB[ ._-]?DL)$', re.I)


def release_title(raw):
    """Return series-title search aliases and an advisory episode number.

    Extract release labels *before* querying AniDB/TVDB. Episode and season
    hints from a filename are NOT canonical identity or download authority.
    In particular do not search standalone "(Batch)" or "(Season S2)" tags.
    """
    if not isinstance(raw, str) or not raw.strip():
        return [], None
    value = PREFIX.sub('', raw).strip()
    episode_match = EP.search(value)
    episode = (next((int(x) for x in (
        episode_match.group('season_ep'), episode_match.group('dash_ep'),
        episode_match.group('word_ep')) if x is not None), None)
        if episode_match else None)
    # An explicit episode token is the safest title boundary. A season token
    # or video encode/quality marker is a weaker boundary for season packs.
    boundaries = [m.start() for m in (episode_match,
                                     SEASON_TOKEN.search(value),
                                     SEASON_WORD.search(value),
                                     RELEASE_TECH.search(value)) if m]
    title = (value[:min(boundaries)] if boundaries else value).strip(' ._-')
    title = TRAIL.sub('', title).strip()
    # Metadata-only parentheticals may occur even when no season token exists.
    parts = [part.strip() for part in META_GROUP.findall(title)]
    safe_parts = [part for part in parts
                  if not METADATA_ONLY.fullmatch(part)]
    title = META_GROUP.sub(lambda m: '' if METADATA_ONLY.fullmatch(m.group(1).strip())
                           else m.group(0), title).strip(' ._-')
    title = re.sub(r'[._]+', ' ', title)
    title = re.sub(r'\s+', ' ', title).strip()
    without_parentheses = META_GROUP.sub('', title)
    without_parentheses = re.sub(r'\s+', ' ', without_parentheses).strip(' ._-')
    # Provider queries never use an isolated packaging tag. Parenthetical
    # alternate names remain optional query aliases only when title-like.
    aliases = [title, without_parentheses]
    for part in safe_parts:
        if (len(part) >= 4 and not re.fullmatch(r'\d{4}', part)
                and not RELEASE_TECH.search(part)
                and not SEASON_WORD.search(part)):
            aliases.append(part)
    return list(dict.fromkeys(x for x in aliases if x)), episode

def norm(s):
    return ''.join(ch for ch in unicodedata.normalize('NFKC', s).casefold() if ch.isalnum())

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

def candidate_titles(record, limit=16, max_length=180):
    """Keep provider-supplied titles only; never substitute our search query."""
    titles = []
    for field in ('name', 'name_translated', 'original_name'):
        value = record.get(field)
        if isinstance(value, str):
            titles.append(value)
    aliases = record.get('aliases') or []
    if isinstance(aliases, list):
        for item in aliases[:32]:
            if isinstance(item, str):
                titles.append(item)
            elif isinstance(item, dict):
                # TVDB aliases may be localized records; only the title is evidence.
                value = item.get('name')
                if isinstance(value, str):
                    titles.append(value)
    seen, result = set(), []
    for title in titles:
        title = ''.join(ch for ch in title.strip() if ch.isprintable())[:max_length]
        key = norm(title)
        if key and key not in seen:
            seen.add(key)
            result.append(title)
            if len(result) >= limit:
                break
    return result


def tvdb_candidates(aliases, api_key):
    token = tvdb_token(api_key)
    results = {}
    errors = []
    for alias in aliases[:3]:
        url = TVDB_URL + '/search?' + urllib.parse.urlencode({'query': alias, 'type': 'series'})
        try:
            response = request_json(url, bearer=token)
            for record in (response.get('data') or [])[:15]:
                if not isinstance(record, dict):
                    continue
                ident = record.get('tvdb_id') or record.get('id')
                if not ident:
                    continue
                key = str(ident)
                names = candidate_titles(record)
                if key not in results:
                    results[key] = {'tvdb_id': key, 'name': names[0] if names else '',
                                    'candidate_titles': names, 'matched_query': alias,
                                    'exact_title_overlap': False}
                else:
                    existing = results[key]['candidate_titles']
                    results[key]['candidate_titles'] = candidate_titles(
                        {'name': existing[0] if existing else '',
                         'aliases': existing[1:] + names})
                    if not results[key]['name'] and names:
                        results[key]['name'] = names[0]
                results[key]['exact_title_overlap'] = bool(
                    {norm(n) for n in results[key]['candidate_titles']} &
                    {norm(a) for a in aliases if isinstance(a, str)})
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
