"""Fail-closed episode mapping verification, separate from V14 confidence points."""
from anime_episode_confidence_v13 import evaluate
from anime_decision_codes import VerificationBlocker, EXPLICIT_ZERO_OFFSET


def verify(report, shadow):
    base = evaluate(report)
    blockers = list(dict.fromkeys(base['blockers']))
    evidence = set(base['evidence'])
    if shadow.get('blockers'):
        blockers.extend(x for x in shadow['blockers'] if x not in blockers)
    if shadow.get('decision') != 'SHADOW_HIGH_CONFIDENCE':
        blockers.append('CONFIDENCE_POLICY_NOT_MET')
    if EXPLICIT_ZERO_OFFSET not in evidence:
        blockers.append(VerificationBlocker.EPISODE_ORDERING_MAPPING_NOT_CONFIRMED.value)
    mappings = [x for x in report.get('mapping_evidence', []) if x.get('anime_lists_pair_match') is True]
    audits = report.get('episode_audit') or []
    checks = report.get('tvdb_episode_checks') or []
    candidate = report.get('episode_candidate')
    result = {'notification_id': report.get('notification_id'), 'episode_identity_verified': False,
              'eligible_for_acquisition': False, 'write_approval_performed': False,
              'confidence_score': shadow.get('score_points'), 'blockers': list(dict.fromkeys(blockers)),
              'decision': 'REVIEW_REQUIRED', 'proposed_mapping': None}
    if len(mappings) == len(audits) == 1 and isinstance(candidate, int) and not isinstance(candidate, bool):
        aid, tid = mappings[0].get('anidb_id'), mappings[0].get('tvdb_id')
        matching = [x for x in checks if str(x.get('tvdb_id')) == str(tid) and
                    x.get('candidate_episode') == candidate and x.get('season') == 1 and
                    x.get('tvdb_episode_exists_at_same_number') is True and
                    len(x.get('tvdb_episode_records') or []) == 1]
        if len(matching) == 1:
            result['proposed_mapping'] = {'anidb_id': aid, 'tvdb_id': tid,
                                          'tvdb_season': 1, 'tvdb_episode': candidate}
    if not result['blockers'] and result['proposed_mapping']:
        result['decision'] = 'AUTO_VERIFIED_CANDIDATE'
        result['episode_identity_verified'] = True
    elif VerificationBlocker.EPISODE_ORDERING_MAPPING_NOT_CONFIRMED.value in result['blockers'] and not base['blockers']:
        result['decision'] = 'AWAITING_MAPPING_EVIDENCE'
    return result
