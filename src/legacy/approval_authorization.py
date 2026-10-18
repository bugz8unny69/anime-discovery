"""Offline administrative authorization gate; no network, database, or API routes.

The administrative signing key must be provisioned separately from the ordinary
ANIME_DISCOVERY_TOKEN. Signatures authenticate requests, not metadata truth.
Production integration must use durable nonce storage and privileged lookups.
"""
import copy
import hashlib
import hmac
import json
import time
from collections.abc import Mapping

DOMAIN = b'anime-discovery/admin-mapping/v1\0'
ACTIONS = frozenset({'APPROVE_MAPPING', 'REVOKE_MAPPING', 'BIND_IDENTITY', 'REVOKE_IDENTITY'})

class AuthorizationError(ValueError):
    pass

def _integer(x):
    return type(x) is int and x > 0

def _canonical(payload):
    try:
        return json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                          allow_nan=False).encode('ascii')
    except (TypeError, ValueError) as exc:
        raise AuthorizationError('INVALID_PAYLOAD') from exc

def candidate_digest(candidate):
    """Hash exact validated reconciliation output; not a proof of its provenance."""
    if not isinstance(candidate, Mapping) or candidate.get('status') != 'CANDIDATE_ONLY' or candidate.get('canonical_mapping_authorized') is not False:
        raise AuthorizationError('INVALID_CANDIDATE')
    for name in ('series_id', 'anilist_id', 'binding_id', 'release_episode', 'canonical_season', 'canonical_episode'):
        if not _integer(candidate.get(name)):
            raise AuthorizationError('INVALID_CANDIDATE')
    if candidate['canonical_season'] != 1 or candidate['canonical_episode'] > 6:
        raise AuthorizationError('OUTSIDE_TRIAL_WINDOW')
    if candidate.get('sources') != ['anidb', 'sonarr']:
        raise AuthorizationError('MISSING_SOURCES')
    return hashlib.sha256(_canonical(dict(candidate))).hexdigest()

def sign_admin_request(*, key, action, actor, nonce, issued_at, expires_at, target):
    """Test/privileged-admin helper. Never expose via ordinary discovery endpoints."""
    if not isinstance(key, bytes) or len(key) < 32:
        raise AuthorizationError('WEAK_ADMIN_KEY')
    payload = {'version': 1, 'action': action, 'actor': actor, 'nonce': nonce,
               'issued_at': issued_at, 'expires_at': expires_at, 'target': copy.deepcopy(target)}
    _validate_payload(payload)
    signature = hmac.new(key, DOMAIN + _canonical(payload), hashlib.sha256).hexdigest()
    return {'payload': payload, 'signature': signature}

def _validate_payload(p):
    if not isinstance(p, dict) or set(p) != {'version','action','actor','nonce','issued_at','expires_at','target'}:
        raise AuthorizationError('INVALID_PAYLOAD')
    if type(p['version']) is not int or p['version'] != 1 or p['action'] not in ACTIONS:
        raise AuthorizationError('INVALID_ACTION')
    if not isinstance(p['actor'], str) or not (1 <= len(p['actor']) <= 128) or not p['actor'].strip():
        raise AuthorizationError('INVALID_ACTOR')
    if not isinstance(p['nonce'], str) or not (16 <= len(p['nonce']) <= 128) or not p['nonce'].isascii() or not p['nonce'].isalnum():
        raise AuthorizationError('INVALID_NONCE')
    if type(p['issued_at']) is not int or type(p['expires_at']) is not int or p['expires_at'] <= p['issued_at'] or p['expires_at'] - p['issued_at'] > 300:
        raise AuthorizationError('INVALID_TIME_WINDOW')
    t = p['target']
    if not isinstance(t, dict) or set(t) != {'series_id','binding_id','candidate_sha256'}:
        raise AuthorizationError('INVALID_TARGET')
    if not _integer(t['series_id']) or not _integer(t['binding_id']):
        raise AuthorizationError('INVALID_TARGET')
    d = t['candidate_sha256']
    if not isinstance(d, str) or len(d) != 64 or any(c not in '0123456789abcdef' for c in d):
        raise AuthorizationError('INVALID_TARGET')

def verify_admin_request(*, envelope, key, expected_action, expected_target, nonce_is_used, now=None):
    """Verify before privileged mutation; caller must atomically persist nonce with mutation.

    nonce_is_used(nonce) is a read-only lookup. This alone is NOT replay-safe under
    concurrency: transaction must insert nonce under UNIQUE constraint and mutate
    approval together. Do not use in a live endpoint without that transaction.
    """
    if not isinstance(key, bytes) or len(key) < 32:
        raise AuthorizationError('WEAK_ADMIN_KEY')
    if not isinstance(envelope, dict) or set(envelope) != {'payload','signature'}:
        raise AuthorizationError('INVALID_ENVELOPE')
    p, sig = envelope['payload'], envelope['signature']
    _validate_payload(p)
    if not isinstance(sig, str) or len(sig) != 64:
        raise AuthorizationError('INVALID_SIGNATURE')
    expected = hmac.new(key, DOMAIN + _canonical(p), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected):
        raise AuthorizationError('INVALID_SIGNATURE')
    if p['action'] != expected_action or p['target'] != expected_target:
        raise AuthorizationError('ACTION_OR_TARGET_MISMATCH')
    if now is None:
        now = int(time.time())
    if type(now) is not int or now < p['issued_at'] - 30 or now >= p['expires_at']:
        raise AuthorizationError('EXPIRED_OR_NOT_YET_VALID')
    if nonce_is_used(p['nonce']):
        raise AuthorizationError('REPLAYED_NONCE')
    return {'actor': p['actor'], 'nonce': p['nonce'], 'action': p['action'], 'target': dict(p['target'])}
