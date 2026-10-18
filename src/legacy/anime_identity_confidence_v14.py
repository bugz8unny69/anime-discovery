"""Configurable, fail-closed V13 evidence scoring (shadow only)."""
import json
from pathlib import Path
from anime_episode_confidence_v13 import evaluate

DEFAULTS = {'enabled': True, 'mode': 'shadow', 'auto_approve_threshold': 90, 'review_threshold': 70,
            'weights': {'verified_series_mapping': 40, 'title_match': 15, 'season_mapping': 15,
                        'episode_number_match': 15, 'tvdb_episode_exists': 15}}
POLICY_VERSION = 'v14.1'

def load_policy(path):
    try:
        raw = json.loads(Path(path).read_text())
    except FileNotFoundError:
        raw = {}
    if not isinstance(raw, dict):
        raise ValueError('Policy must be a JSON object')
    if set(raw) - set(DEFAULTS):
        raise ValueError('Unknown policy keys')
    cfg = dict(DEFAULTS)
    cfg.update({k: v for k, v in raw.items() if k != 'weights'})
    cfg['weights'] = dict(DEFAULTS['weights'])
    cfg['weights'].update(raw.get('weights', {}))
    if set(cfg['weights']) != set(DEFAULTS['weights']):
        raise ValueError('Invalid scoring weight keys')
    if type(cfg['enabled']) is not bool or cfg['mode'] != 'shadow':
        raise ValueError('V14 supports enabled=true/false and shadow mode only')
    if any(type(v) is not int or v < 0 or v > 100 for v in cfg['weights'].values()):
        raise ValueError('Weights must be integers 0..100')
    if sum(cfg['weights'].values()) != 100:
        raise ValueError('Weights must total 100')
    a, r = cfg['auto_approve_threshold'], cfg['review_threshold']
    if type(a) is not int or type(r) is not int or not 0 <= r < a <= 100:
        raise ValueError('Require 0 <= review_threshold < auto_approve_threshold <= 100')
    return cfg

def score(report, policy):
    baseline = evaluate(report)
    reasons = set(baseline['evidence'])
    w = policy['weights']
    points = (w['verified_series_mapping'] if 'INDEPENDENT_SERIES_MAPPING_AND_ANIMATION_TITLE_MATCH' in reasons else 0)
    # V13 combines independent series mapping and title match in one validated evidence assertion.
    if 'INDEPENDENT_SERIES_MAPPING_AND_ANIMATION_TITLE_MATCH' in reasons:
        points += w['title_match']
    points += w['season_mapping'] if 'DEFAULT_SEASON_ONE' in reasons else 0
    points += w['episode_number_match'] if 'SINGLE_EPISODE_NUMBER_PARSED' in reasons else 0
    points += w['tvdb_episode_exists'] if 'TVDB_SEASON_ONE_EPISODE_RECORD_EXISTS' in reasons else 0
    blockers = baseline['blockers']
    if not policy['enabled']:
        decision = 'SHADOW_DISABLED'
    elif blockers:
        decision = 'SHADOW_BLOCKED'
    elif points >= policy['auto_approve_threshold']:
        decision = 'SHADOW_HIGH_CONFIDENCE'
    elif points < policy['review_threshold']:
        decision = 'SHADOW_REVIEW_CANDIDATE'
    else:
        decision = 'SHADOW_MORE_EVIDENCE'
    return {'policy_version': POLICY_VERSION, 'mode': 'SHADOW_ONLY', 'notification_id': report.get('notification_id'),
            'score_points': points, 'score_max': 100, 'score_is_probability': False,
            'decision': decision, 'blockers': blockers, 'evidence': sorted(reasons),
            'policy': policy, 'would_approve_episode_mapping': decision == 'SHADOW_HIGH_CONFIDENCE',
            'episode_identity_verified': False, 'eligible_for_acquisition': False, 'write_approval_performed': False}
