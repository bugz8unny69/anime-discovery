#!/usr/bin/env python3
"""Read-only episode/season rule audit of the v4 identity cross-reference."""
import argparse
import json
import os
import re
import tempfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

from anime_config_runtime import data_path
from anime_identity_mapping_v4 import evaluate
from anime_identity_crosscheck_v3 import run as run_v3

INT = re.compile(r'^-?\d+$')


def audit(report, xml_bytes):
    result = evaluate(report, xml_bytes)
    result['episode_audit'] = []
    result['verified_identity'] = False
    result['usable_for_automation'] = False
    root = ET.fromstring(xml_bytes)
    episode = result.get('episode_candidate')
    for pair in result.get('mapping_evidence', []):
        if not (pair['anime_lists_pair_match'] and pair['media_type'] == 'ANIMATION'
                and pair['title_corroborated']):
            continue
        aid, tid = pair['anidb_id'], pair['tvdb_id']
        nodes = [n for n in root.findall('anime') if n.get('anidbid') == aid and n.get('tvdbid') == tid]
        for node in nodes:
            season = node.get('defaulttvdbseason')
            offset = node.get('episodeoffset')
            mapping = node.find('mapping-list')
            rules = []
            if mapping is not None:
                for child in mapping.findall('mapping'):
                    rules.append({'attributes': dict(child.attrib), 'text': (child.text or '').strip()})
            problems = []
            if not isinstance(episode, int) or episode < 1:
                problems.append('EPISODE_NOT_POSITIVE_INTEGER')
            if season is None or not season.isdecimal() or int(season) < 0:
                problems.append('DEFAULT_SEASON_MISSING_OR_INVALID')
            if offset is not None and not INT.fullmatch(offset):
                problems.append('INVALID_EPISODE_OFFSET')
            if rules:
                problems.append('EPISODE_SPECIFIC_MAPPING_REQUIRES_AUDIT')
            # A missing offset is NOT silently treated as an authoritative zero.
            if offset is None:
                problems.append('EPISODE_OFFSET_NOT_EXPLICIT')
            mapped = (episode + int(offset)) if isinstance(episode, int) and offset is not None and INT.fullmatch(offset) else None
            if mapped is not None and mapped < 1:
                problems.append('MAPPED_EPISODE_OUT_OF_RANGE')
            result['episode_audit'].append({
                'anidb_id': aid, 'tvdb_id': tid, 'episode_candidate': episode,
                'default_tvdb_season': season, 'episode_offset': offset,
                'mapped_tvdb_episode_if_explicit': mapped,
                'episode_specific_rules': rules,
                'audit_flags': problems,
                'series_mapping_corroborated': True,
                'episode_mapping_verified': False,
            })
    if result.get('issues'):
        result['next_action'] = 'RETRY_LOOKUP; NO_STATUS_CHANGE'
    elif len(result['episode_audit']) != 1:
        result['next_action'] = 'MAPPING_AMBIGUOUS_OR_MISSING; NO_STATUS_CHANGE'
    elif result['episode_audit'][0]['audit_flags']:
        result['next_action'] = 'SERIES_CORROBORATED; EPISODE_AUDIT_REQUIRED; NO_STATUS_CHANGE'
    else:
        # Mapping arithmetic alone does not confirm TVDB episode existence or season identity.
        result['next_action'] = 'EPISODE_RULES_PARSE; TVDB_EPISODE_EXISTENCE_CHECK_REQUIRED; NO_STATUS_CHANGE'
    return result


def write_json_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.identity-audit-', suffix='.json', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as out:
            json.dump(value, out, indent=2, ensure_ascii=False)
            out.write('\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--notification-id', type=int, default=1)
    p.add_argument('--mapping-file', type=Path, default=None)
    p.add_argument('--output', type=Path, required=True, help='Write JSON to a shareable file')
    args = p.parse_args()
    report = None
    try:
        report = run_v3(args.notification_id)
        if report.get('issues'):
            report['next_action'] = 'RETRY_LOOKUP; NO_STATUS_CHANGE'
        else:
            report = audit(report, (args.mapping_file or data_path('anime-lists.xml')).read_bytes())
        report['audit_version'] = 5
        report['generated_utc'] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        report = {'audit_version': 5, 'notification_id': args.notification_id,
                  'issues': [f'{type(exc).__name__}: {exc}'], 'verified_identity': False,
                  'usable_for_automation': False, 'next_action': 'RETRY_AUDIT; NO_STATUS_CHANGE'}
    write_json_atomic(args.output, report)
    print(f'Wrote {args.output}; next_action={report["next_action"]}')
    return 0 if not report.get('issues') else 2


if __name__ == '__main__':
    raise SystemExit(main())
