#!/usr/bin/env python3
"""Offline, read-only series/episode decision from a v6 JSON report."""
import argparse
import json
from pathlib import Path


def decide(report):
    mappings = [m for m in report.get('mapping_evidence', []) if m.get('anime_lists_pair_match') and m.get('media_type') == 'ANIMATION' and m.get('title_corroborated')]
    audits = report.get('episode_audit') or []
    checks = report.get('tvdb_episode_checks') or []
    result = {'notification_id': report.get('notification_id'), 'source_audit_version': report.get('audit_version'),
              'series_identity_verified': False, 'episode_identity_verified': False,
              'eligible_for_acquisition': False, 'write_performed': False, 'status_unchanged': report.get('status_unchanged'),
              'issues': [], 'decision': 'RETRY_OR_REVIEW'}
    if report.get('issues'):
        result['issues'].append('UPSTREAM_LOOKUP_ISSUES')
    elif len(mappings) != 1 or len(audits) != 1:
        result['issues'].append('SERIES_MAPPING_NOT_UNIQUE')
    else:
        m, a = mappings[0], audits[0]
        if (str(m['anidb_id']), str(m['tvdb_id'])) != (str(a.get('anidb_id')), str(a.get('tvdb_id'))):
            result['issues'].append('MAPPING_AUDIT_DISAGREES')
        else:
            result['series_identity_verified'] = True
            result['series'] = {'anidb_id': str(m['anidb_id']), 'tvdb_id': str(m['tvdb_id']), 'mapping_source': report.get('anime_lists_source')}
            matching = [c for c in checks if str(c.get('tvdb_id')) == str(m['tvdb_id']) and c.get('tvdb_episode_exists_at_same_number')]
            result['tvdb_episode_exists'] = bool(matching)
            if not matching:
                result['issues'].append('TVDB_EPISODE_NOT_CONFIRMED')
            if a.get('episode_offset') is None:
                result['issues'].append('ANIDB_TO_TVDB_EPISODE_OFFSET_UNSPECIFIED')
            if a.get('episode_specific_rules'):
                result['issues'].append('EPISODE_SPECIFIC_RULES_REQUIRE_INTERPRETATION')
            # No external AniDB episode confirmation is available in v6.
            result['issues'].append('ANIDB_EPISODE_IDENTITY_NOT_INDEPENDENTLY_CONFIRMED')
            result['decision'] = 'SERIES_VERIFIED_EPISODE_PENDING'
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = decide(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(f'Wrote {args.output}: {result["decision"]}')

if __name__ == '__main__':
    main()
