#!/usr/bin/env python3
"""Read-only AniDB title catalog + authenticated TVDB series evidence checker.

Does not change identity mappings or authorize automation.
"""
import argparse
import gzip
import json
import os
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from anime_identity_catalog import audit, read_catalog
from anime_config_runtime import get as config_get

TITLES_URL = 'https://anidb.net/api/anime-titles.xml.gz'
TVDB_URL = 'https://api4.thetvdb.com/v4'

def normalized(value):
    return re.sub(r'[^a-z0-9]+', '', str(value).casefold())

def anidb_titles(blob, anime_ids):
    """Read the official AniDB title index, not an episode mapping."""
    if blob[:2] == b'\x1f\x8b':
        blob = gzip.decompress(blob)
    wanted = {str(x) for x in anime_ids}
    found = {}
    for _, node in ET.iterparse(__import__('io').BytesIO(blob), events=('end',)):
        if node.tag == 'anime':
            aid = node.attrib.get('aid')
            if aid in wanted:
                found[aid] = sorted({(n.text or '').strip() for n in node.findall('title') if (n.text or '').strip()})
            node.clear()
    return found

def request_json(url, payload=None, bearer=None):
    headers = {'Accept': 'application/json', 'User-Agent': 'AnimeDiscoveryIdentityVerifier/1.0'}
    if payload is not None:
        headers['Content-Type'] = 'application/json'
    if bearer:
        headers['Authorization'] = 'Bearer ' + bearer
    req = urllib.request.Request(url, data=json.dumps(payload).encode() if payload is not None else None, headers=headers)
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.load(resp)

def tvdb_token(api_key, pin=''):
    payload = {'apikey': api_key}
    if pin:
        payload['pin'] = pin
    data = request_json(TVDB_URL + '/login', payload)
    token = data.get('data', {}).get('token')
    if not token:
        raise ValueError('TVDB login did not return a token')
    return token

def tvdb_series(series_id, token):
    data = request_json(f'{TVDB_URL}/series/{int(series_id)}/extended', bearer=token)
    record = data.get('data') or {}
    if str(record.get('id')) != str(series_id):
        raise ValueError('TVDB returned an unexpected series ID')
    names = {str(record.get('name') or '').strip()}
    for a in record.get('aliases') or []:
        if isinstance(a, dict):
            names.add(str(a.get('name') or '').strip())
        elif isinstance(a, str):
            names.add(a.strip())
    for translation in (record.get('translations') or {}).get('nameTranslations', []):
        if isinstance(translation, dict):
            names.add(str(translation.get('name') or '').strip())
    return {'id': str(series_id), 'titles': sorted(n for n in names if n), 'year': str(record.get('year') or '')}

def compare(anidb, tvdb):
    a = {normalized(t) for t in anidb if normalized(t)}
    b = {normalized(t) for t in tvdb['titles'] if normalized(t)}
    overlap = a & b
    return {'title_overlap': bool(overlap), 'matching_normalized_titles': sorted(overlap),
            'status': 'TITLE_CORROBORATED_REVIEW_REQUIRED' if overlap else 'NEEDS_REVIEW'}

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--file', default=os.getenv('ANIME_IDENTITY_MAPPINGS', '/var/lib/anime-discovery/identity-mappings.json'))
    p.add_argument('--titles-cache', default='/var/lib/anime-discovery/anidb-titles.xml.gz')
    p.add_argument('--refresh-titles', action='store_true', help='Download official AniDB title index to local cache')
    args = p.parse_args(argv)
    report = audit(read_catalog(args.file))
    if report['issues']:
        print('Identity audit errors; refusing verification:', *report['issues'], sep='\n', file=sys.stderr)
        return 2
    ids = {r['anidb_id'] for r in report['records']}
    if not ids:
        print('No saved identity suggestions to check.')
        return 0
    cache = Path(args.titles_cache)
    try:
        if args.refresh_titles:
            req = urllib.request.Request(TITLES_URL, headers={'User-Agent':'AnimeDiscoveryIdentityVerifier/1.0'})
            with urllib.request.urlopen(req, timeout=30) as response:
                content = response.read(32 * 1024 * 1024 + 1)
            if len(content) > 32 * 1024 * 1024:
                raise ValueError('AniDB title index exceeds safety size limit')
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(content)
        titles = anidb_titles(cache.read_bytes(), ids)
    except (OSError, ValueError, ET.ParseError) as exc:
        print(f'AniDB title catalog unavailable: {exc}. Run with --refresh-titles.', file=sys.stderr)
        return 2
    api_key = (config_get('tvdb.api_key') or '').strip() if config_get('tvdb.enabled') else ''
    token = None
    if api_key:
        try:
            token = tvdb_token(api_key, os.getenv('ANIME_TVDB_PIN', ''))
        except (ValueError, urllib.error.URLError, KeyError) as exc:
            print(f'TVDB authentication unavailable: {exc}', file=sys.stderr)
    else:
        print('TVDB disabled or API key not configured: AniDB title checks only; no TVDB verification.')
    for row in report['records']:
        aid, tid = row['anidb_id'], row['tvdb_id']
        a = titles.get(aid, [])
        result = {'review_id': row['review_id'], 'anidb_id': aid, 'tvdb_id': tid,
                  'anidb_found': bool(a), 'anidb_titles': a, 'status': 'NEEDS_REVIEW',
                  'usable_for_automation': False}
        if token and a:
            try:
                t = tvdb_series(tid, token)
                result['tvdb'] = t
                result.update(compare(a, t))
            except (ValueError, urllib.error.URLError, KeyError) as exc:
                result['tvdb_error'] = str(exc)
        print(json.dumps(result, ensure_ascii=False))
    print('READ ONLY: No identity was approved for downloads, Sonarr, or Shoko.', file=sys.stderr)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
