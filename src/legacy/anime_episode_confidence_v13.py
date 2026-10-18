#!/usr/bin/env python3
"""Read-only, explainable episode mapping SHADOW evaluation; never authorizes acquisition."""
import argparse
import json
import re
from pathlib import Path
from anime_decision_codes import EXPLICIT_ZERO_OFFSET

RISK = re.compile(r'(?i)(?:\b(?:special|ova|oad|ona|movie|film|recap|batch|complete|season\s*[2-9]|s0[2-9]|cour\s*[2-9]|part\s*[2-9])\b|\b(?:e|ep)\s*\d+\s*[-~]\s*\d+\b)')


def evaluate(report):
    reasons = []
    blockers = []
    mapping = [x for x in report.get('mapping_evidence', []) if x.get('anime_lists_pair_match') is True]
    audits = report.get('episode_audit') or []
    checks = report.get('tvdb_episode_checks') or []
    if report.get('issues'):
        blockers.append('UPSTREAM_ISSUES')
    if len(mapping) != 1 or len(audits) != 1:
        blockers.append('NON_UNIQUE_SERIES_MAPPING_OR_AUDIT')
    score = 0
    selected = mapping[0] if len(mapping) == 1 else None
    audit = audits[0] if len(audits) == 1 else None
    if selected and audit:
        aid, tid = str(selected.get('anidb_id')), str(selected.get('tvdb_id'))
        if (aid, tid) != (str(audit.get('anidb_id')), str(audit.get('tvdb_id'))):
            blockers.append('MAPPING_AUDIT_CONFLICT')
        elif selected.get('media_type') != 'ANIMATION' or not selected.get('title_corroborated'):
            blockers.append('ANIME_TYPE_OR_TITLE_NOT_CORROBORATED')
        else:
            score += 55
            reasons.append('INDEPENDENT_SERIES_MAPPING_AND_ANIMATION_TITLE_MATCH')
        rules = selected.get('anime_lists_records') or []
        if len(rules) != 1:
            blockers.append('MULTIPLE_OR_MISSING_MAPPING_RECORDS')
        if audit.get('episode_specific_rules'):
            blockers.append('EPISODE_OVERRIDES_REQUIRE_INTERPRETATION')
        if audit.get('audit_flags') and any(flag != 'EPISODE_OFFSET_NOT_EXPLICIT' for flag in audit['audit_flags']):
            blockers.append('UNRECOGNIZED_MAPPING_FLAGS')
        season = audit.get('default_tvdb_season')
        if str(season) != '1':
            blockers.append('NON_STANDARD_TVDB_SEASON')
        else:
            score += 10
            reasons.append('DEFAULT_SEASON_ONE')
        offset = audit.get('episode_offset')
        if offset is not None:
            try:
                if int(offset) != 0:
                    blockers.append('NONZERO_OFFSET_REQUIRES_EXPLICIT_MAPPING')
                else:
                    score += 10
                    reasons.append(EXPLICIT_ZERO_OFFSET)
            except (ValueError, TypeError):
                blockers.append('INVALID_EPISODE_OFFSET')
        else:
            reasons.append('MISSING_OFFSET_TREATED_AS_UNPROVEN_ZERO_HYPOTHESIS')
        ep = report.get('episode_candidate')
        if not isinstance(ep, int) or not (1 <= ep <= 1000) or ep != audit.get('episode_candidate'):
            blockers.append('INVALID_OR_CONFLICTING_EPISODE_NUMBER')
        else:
            score += 10
            reasons.append('SINGLE_EPISODE_NUMBER_PARSED')
        matches = [x for x in checks if str(x.get('tvdb_id')) == tid and x.get('tvdb_episode_exists_at_same_number') is True and x.get('candidate_episode') == ep and x.get('season') == 1]
        if len(matches) != 1 or len(matches[0].get('tvdb_episode_records') or []) != 1:
            blockers.append('TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED')
        else:
            score += 15
            reasons.append('TVDB_SEASON_ONE_EPISODE_RECORD_EXISTS')
    release = report.get('release_name') or ''
    if not release:
        blockers.append('RELEASE_NAME_MISSING')
    elif RISK.search(release):
        blockers.append('SPECIAL_SEQUEL_BATCH_OR_MULTI_EPISODE_RELEASE')
    if len(mapping) > 1:
        blockers.append('CONFLICTING_CROSS_DATABASE_LINKS')
    # Confidence is an evidence rubric, NOT a calibrated probability.
    would_approve = score >= 90 and not blockers
    return {
        'version': 13, 'notification_id': report.get('notification_id'),
        'mode': 'SHADOW_ONLY', 'score_points': score, 'score_max': 100,
        'score_is_probability': False, 'would_approve_episode_mapping': would_approve,
        'decision': 'SHADOW_HIGH_CONFIDENCE' if would_approve else ('SHADOW_BLOCKED' if blockers else 'SHADOW_MORE_EVIDENCE'),
        'evidence': reasons, 'blockers': blockers,
        'episode_identity_verified': False, 'eligible_for_acquisition': False,
        'write_performed': False, 'inbox_modified': False, 'downloads_enabled': False,
        'policy_note': 'No episode approval is written. Unspecified offset is a hypothesis, not an established cross-reference.'
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    result = evaluate(json.loads(args.input.read_text(encoding='utf-8')))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    print(json.dumps({'decision': result['decision'], 'score_points': result['score_points'], 'blockers': result['blockers']}))

if __name__ == '__main__':
    main()
