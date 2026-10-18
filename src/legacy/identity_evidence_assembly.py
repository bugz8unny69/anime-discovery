"""Phase 2X-P offline evidence assembly. No network, DB writes, or approvals.

Inputs must originate from privileged storage and adapters, never RSS/API payloads.
An explicit administrator-reviewed cross-reference is required; titles do not bind IDs.
"""
import hashlib
import json
from collections.abc import Mapping
from episode_reconciliation import reconcile, ReconciliationError

class AssemblyError(ValueError):
    pass

def _pos(x):
    return type(x) is int and x > 0

def _digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest()

def assemble(*, release_title, series_id, anilist_id, binding, cross_reference,
             anilist_snapshot, sonarr_snapshot, anidb_snapshot):
    """Build a candidate from explicit, controller-side identity and episode evidence.

    Cross-reference is an administrator-reviewed *record*, not a cryptographic proof.
    Snapshots must be fetched and supplied by privileged adapters. This function
    checks consistency, not actual API authentication or independent provenance.
    """
    if not _pos(series_id) or not _pos(anilist_id):
        raise AssemblyError('INVALID_ID')
    if not isinstance(binding, Mapping) or binding.get('series_id') != series_id or binding.get('provider') != 'anilist' or binding.get('provider_id') != anilist_id or binding.get('state') != 'ACTIVE' or not _pos(binding.get('binding_id')):
        raise AssemblyError('IDENTITY_NOT_BOUND')
    if not isinstance(cross_reference, Mapping) or cross_reference.get('series_id') != series_id or cross_reference.get('anilist_id') != anilist_id or cross_reference.get('binding_id') != binding['binding_id'] or not _pos(cross_reference.get('sonarr_series_id')) or not _pos(cross_reference.get('anidb_anime_id')) or cross_reference.get('status') != 'ADMIN_REVIEWED' or not isinstance(cross_reference.get('audit_ref'), str) or not cross_reference['audit_ref'].strip():
        raise AssemblyError('CROSS_REFERENCE_NOT_REVIEWED')
    if not isinstance(anilist_snapshot, Mapping) or anilist_snapshot.get('id') != anilist_id or anilist_snapshot.get('identity_only') is not True or anilist_snapshot.get('canonical_mapping_authorized') is not False:
        raise AssemblyError('ANILIST_IDENTITY_MISMATCH')
    if not isinstance(sonarr_snapshot, Mapping) or sonarr_snapshot.get('sonarr_series_id') != cross_reference['sonarr_series_id'] or sonarr_snapshot.get('canonical_mapping_authorized') is not False:
        raise AssemblyError('SONARR_IDENTITY_MISMATCH')
    if not isinstance(anidb_snapshot, Mapping) or anidb_snapshot.get('anidb_anime_id') != cross_reference['anidb_anime_id'] or anidb_snapshot.get('canonical_mapping_authorized') is not False:
        raise AssemblyError('ANIDB_IDENTITY_MISMATCH')
    # Episode lists here are normalized by separately privileged, source-specific
    # adapters; they must not be provided by indexers or discovery callers.
    sonarr_entries = sonarr_snapshot.get('normalized_entries')
    anidb_entries = anidb_snapshot.get('normalized_entries')
    if not isinstance(sonarr_entries, list) or not isinstance(anidb_entries, list):
        raise AssemblyError('NORMALIZED_EPISODES_REQUIRED')
    evidence = [
        {'provider': 'sonarr', 'series_id': series_id, 'anilist_id': anilist_id, 'entries': sonarr_entries},
        {'provider': 'anidb', 'series_id': series_id, 'anilist_id': anilist_id, 'entries': anidb_entries},
    ]
    try:
        candidate = reconcile(release_title=release_title, series_id=series_id,
                              anilist_id=anilist_id, binding=binding, episode_evidence=evidence)
    except ReconciliationError as exc:
        raise AssemblyError(str(exc)) from exc
    identity = {'series_id': series_id, 'anilist_id': anilist_id, 'binding_id': binding['binding_id'],
                'sonarr_series_id': cross_reference['sonarr_series_id'],
                'anidb_anime_id': cross_reference['anidb_anime_id'],
                'audit_ref': cross_reference['audit_ref']}
    snapshot_fingerprints = {'anilist': _digest(anilist_snapshot), 'sonarr': _digest(sonarr_snapshot),
                             'anidb': _digest(anidb_snapshot)}
    result = {'identity': identity, 'candidate': candidate, 'snapshot_sha256': snapshot_fingerprints}
    return {'status': 'CANDIDATE_ONLY', 'canonical_mapping_authorized': False,
            'evidence_sha256': _digest(result), **result}
