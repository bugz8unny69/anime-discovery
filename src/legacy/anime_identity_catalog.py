#!/usr/bin/env python3
"""Read-only audit/export of dashboard identity suggestions. Never authorizes automation."""
import argparse
import json
import os
import re
from pathlib import Path

DEFAULT = '/var/lib/anime-discovery/identity-mappings.json'

class CatalogError(ValueError):
    pass

def read_catalog(path):
    try:
        data = json.loads(Path(path).read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        raise CatalogError(f'Cannot read mapping file: {exc}') from exc
    if not isinstance(data, dict):
        raise CatalogError('Expected a JSON object keyed by inbox review ID')
    return data

def audit(data):
    rows=[]; issues=[]; anidb={}; tvdb={}; pairs={}
    for review_id, entry in sorted(data.items(), key=lambda kv: str(kv[0])):
        if not isinstance(entry,dict):
            issues.append(f'Review {review_id}: mapping is not an object'); continue
        aid=str(entry.get('anidb_id','')); tid=str(entry.get('tvdb_id',''))
        if not re.fullmatch(r'[1-9][0-9]{0,11}',aid) or not re.fullmatch(r'[1-9][0-9]{0,11}',tid):
            issues.append(f'Review {review_id}: invalid AniDB or TVDB ID'); continue
        if entry.get('usable_for_automation') is True:
            issues.append(f'Review {review_id}: unsafe automation flag; manual entries are not verified')
        for name, lookup, ident, counterpart in [('AniDB',anidb,aid,tid),('TVDB',tvdb,tid,aid)]:
            if ident in lookup and lookup[ident][0]!=counterpart:
                issues.append(f'Review {review_id}: {name} ID {ident} conflicts with review {lookup[ident][1]}')
            lookup.setdefault(ident,(counterpart,review_id))
        pairs.setdefault((aid,tid),[]).append(review_id)
        rows.append({'review_id':str(review_id),'anidb_id':aid,'tvdb_id':tid,
                     'release_name':str(entry.get('release_name','')),
                     'verification':str(entry.get('verification','UNKNOWN')),
                     'usable_for_automation':False})
    return {'schema_version':1,'identity_only':True,'usable_for_automation':False,
            'records':rows,'unique_pairs':len(pairs),'issues':issues}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file',default=os.environ.get('ANIME_IDENTITY_MAPPINGS',DEFAULT))
    parser.add_argument('--json',action='store_true',help='Print machine-readable audit (read-only)')
    args=parser.parse_args()
    try: report=audit(read_catalog(args.file))
    except CatalogError as exc: parser.error(str(exc))
    if args.json: print(json.dumps(report,indent=2))
    else:
        print(f"Identity suggestions: {len(report['records'])}; unique ID pairs: {report['unique_pairs']}")
        for row in report['records']:
            print(f"  review #{row['review_id']}: AniDB {row['anidb_id']} / TVDB {row['tvdb_id']} — {row['verification']}")
        for issue in report['issues']: print('  WARNING:',issue)
        print('No mapping is authorized for downloads, Sonarr, or Shoko.')
    return 2 if report['issues'] else 0

if __name__=='__main__': raise SystemExit(main())
