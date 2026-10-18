#!/usr/bin/env python3
"""Read-only Anime-Lists cross-reference probe. Never writes identity/status state."""
import argparse
import json
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

from anime_config_runtime import data_path
from anime_identity_crosscheck_v3 import run as run_v3

SOURCE = 'https://raw.githubusercontent.com/Anime-Lists/anime-lists/master/anime-list.xml'
MAX_BYTES = 16 * 1024 * 1024


def download(url=SOURCE):
    req = urllib.request.Request(url, headers={'User-Agent': 'AnimeDiscoveryIdentityMappingProbe/4.0'})
    with urllib.request.urlopen(req, timeout=35) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Mapping file exceeds size limit')
    return data


def mappings(xml_bytes, anidb_id):
    root = ET.fromstring(xml_bytes)
    if root.tag != 'anime-list':
        raise ValueError('Unexpected Anime-Lists XML root')
    out = []
    for node in root.findall('anime'):
        if node.get('anidbid') != str(anidb_id):
            continue
        # These are mapping *attributes*, not evidence of a single TVDB episode/season.
        out.append({key: node.get(key) for key in (
            'anidbid', 'tvdbid', 'defaulttvdbseason', 'episodeoffset', 'tmdbid', 'imdbid'
        ) if node.get(key) is not None})
    return out


def evaluate(report, xml_bytes):
    report = dict(report)
    ids = sorted({str(p['anidb_id']) for p in report.get('crosscheck_v3', [])})
    report['anime_lists_source'] = SOURCE
    report['anime_lists_mappings'] = {aid: mappings(xml_bytes, aid) for aid in ids}
    report['mapping_evidence'] = []
    for pair in report.get('crosscheck_v3', []):
        aid, tid = str(pair['anidb_id']), str(pair['tvdb_id'])
        rows = report['anime_lists_mappings'][aid]
        matching = [r for r in rows if r.get('tvdbid') == tid]
        report['mapping_evidence'].append({
            'anidb_id': aid, 'tvdb_id': tid,
            'anime_lists_pair_match': bool(matching),
            'anime_lists_records': matching,
            'media_type': pair['media_type'],
            'title_corroborated': pair['title_corroborated'],
        })
    eligible = [p for p in report['mapping_evidence'] if p['anime_lists_pair_match']
                and p['media_type'] == 'ANIMATION' and p['title_corroborated']]
    conflicts = [p for p in report['mapping_evidence'] if p['anime_lists_pair_match']
                 and p['media_type'] in ('LIVE_ACTION', 'CONFLICTING_MEDIA_TYPE')]
    report['verified_identity'] = False
    report['usable_for_automation'] = False
    if report.get('issues'):
        action = 'RETRY_LOOKUP; NO_STATUS_CHANGE'
    elif conflicts or len(eligible) > 1:
        action = 'MAPPING_CONFLICT; MANUAL_REVIEW_REQUIRED'
    elif len(eligible) == 1:
        action = 'INDEPENDENT_MAPPING_CORROBORATED; AUDIT_SEASON_RULES_BEFORE_PERSISTING'
    else:
        action = 'NO_CORROBORATED_MAPPING; MANUAL_REVIEW_CANDIDATE'
    report['next_action'] = action
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--notification-id', type=int, default=1)
    parser.add_argument('--refresh-mappings', action='store_true')
    parser.add_argument('--mapping-file', type=Path, help='Optional local Anime-Lists XML fixture')
    args = parser.parse_args()
    report = run_v3(args.notification_id)
    if report.get('issues'):
        report['next_action'] = 'RETRY_LOOKUP; NO_STATUS_CHANGE'
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return
    cache = args.mapping_file or data_path('anime-lists.xml')
    try:
        if args.refresh_mappings:
            if args.mapping_file:
                parser.error('Do not combine --mapping-file and --refresh-mappings')
            data = download()
            ET.fromstring(data)  # validate before caching
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(data)
        else:
            data = cache.read_bytes()
        report = evaluate(report, data)
    except (OSError, ValueError, ET.ParseError) as exc:
        report['issues'].append('Anime-Lists unavailable/invalid: ' + type(exc).__name__)
        report['next_action'] = 'RETRY_MAPPING; NO_STATUS_CHANGE'
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
