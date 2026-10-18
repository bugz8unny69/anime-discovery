"""Read-only identity evidence assembly. Never grants acquisition permission."""
from pathlib import Path
import urllib.error

from anime_identity_catalog import audit, read_catalog
from anime_identity_verify import anidb_titles, compare, tvdb_series, tvdb_token

DEFAULT_CACHE = '/var/lib/anime-discovery/anidb-titles.xml.gz'

def evidence(path, cache=DEFAULT_CACHE, tvdb_key='', tvdb_pin=''):
    report = audit(read_catalog(path))
    if report['issues']:
        return {'issues': report['issues'], 'records': [], 'usable_for_automation': False}
    records = report['records']
    if not records:
        return {'issues': [], 'records': [], 'usable_for_automation': False}
    blob = Path(cache).read_bytes()
    titles = anidb_titles(blob, {r['anidb_id'] for r in records})
    token = None
    auth_error = None
    if tvdb_key:
        try:
            token = tvdb_token(tvdb_key, tvdb_pin)
        except (ValueError, KeyError, urllib.error.URLError) as exc:
            auth_error = type(exc).__name__
    output = []
    for r in records:
        a = titles.get(r['anidb_id'], [])
        item = {'review_id': r['review_id'], 'anidb_id': r['anidb_id'],
                'tvdb_id': r['tvdb_id'], 'anidb_found': bool(a),
                'anidb_titles': a, 'status': 'NEEDS_REVIEW',
                'usable_for_automation': False}
        if auth_error:
            item['tvdb_status'] = 'UNAVAILABLE'
        if token and a:
            try:
                t = tvdb_series(r['tvdb_id'], token)
                item['tvdb'] = t
                item.update(compare(a, t))
            except (ValueError, KeyError, urllib.error.URLError):
                item['tvdb_status'] = 'UNAVAILABLE'
        output.append(item)
    return {'issues': [], 'records': output, 'usable_for_automation': False}
