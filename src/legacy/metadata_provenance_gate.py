"""2X-AH: offline provenance decision gate. No network, DB writes, or approvals.

This module deliberately cannot mint production trust. Adapter provenance must be
implemented and verified separately; fixture evidence is never authorization.
"""
from dataclasses import dataclass
from typing import Optional, Tuple

class ProvenanceError(ValueError):
    pass

@dataclass(frozen=True)
class EpisodeEvidence:
    provider: str
    provider_series_id: int
    canonical_season: int
    canonical_episode: int
    release_episode: int
    kind: str
    observed_at: int
    record_id: str
    authenticated_transport: bool = False
    source_attested: bool = False

@dataclass(frozen=True)
class IdentityEvidence:
    anilist_id: int
    sonarr_series_id: int
    anidb_series_id: int
    cross_reference_attested: bool = False

@dataclass(frozen=True)
class ProvenanceDecision:
    status: str
    reasons: Tuple[str, ...]
    candidate: Optional[Tuple[int, int, int]] = None
    automatic_approval_authorized: bool = False
    manual_approval_authorized: bool = False


def evaluate(identity, records, *, now, max_age=86400):
    """Check candidate consistency; never treat self-declared flags as trust.

    A PASS means candidate is suitable for later independently authenticated
    review, not that any provider, cross-reference, or administrator is trusted.
    """
    if type(now) is not int or now <= 0 or type(max_age) is not int or max_age <= 0:
        raise ProvenanceError('INVALID_CLOCK')
    if not isinstance(identity, IdentityEvidence):
        raise ProvenanceError('INVALID_IDENTITY')
    if any(type(x) is not int or x <= 0 for x in
           (identity.anilist_id, identity.sonarr_series_id, identity.anidb_series_id)):
        raise ProvenanceError('INVALID_IDENTIFIERS')
    if not isinstance(records, (tuple, list)):
        raise ProvenanceError('INVALID_RECORDS')
    reasons = []
    if not identity.cross_reference_attested:
        reasons.append('CROSS_REFERENCE_NOT_ATTESTED')
    if len(records) != 2 or any(not isinstance(x, EpisodeEvidence) for x in records):
        reasons.append('TWO_SOURCE_RECORDS_REQUIRED')
        return ProvenanceDecision('BLOCKED', tuple(reasons))
    by_provider = {r.provider: r for r in records}
    if set(by_provider) != {'sonarr', 'anidb'} or len(by_provider) != 2:
        reasons.append('INDEPENDENT_PROVIDERS_REQUIRED')
    if any(type(r.provider_series_id) is not int or r.provider_series_id <= 0 or
           type(r.release_episode) is not int or r.release_episode <= 0 or
           type(r.canonical_season) is not int or r.canonical_season != 1 or
           type(r.canonical_episode) is not int or not 1 <= r.canonical_episode <= 6 or
           r.kind != 'REGULAR' or not isinstance(r.record_id, str) or not r.record_id.strip()
           for r in records):
        reasons.append('INVALID_EPISODE_RECORD')
    if set(by_provider) == {'sonarr', 'anidb'}:
        if (by_provider['sonarr'].provider_series_id != identity.sonarr_series_id or
            by_provider['anidb'].provider_series_id != identity.anidb_series_id):
            reasons.append('SERIES_ID_MISMATCH')
    candidates = {(r.release_episode, r.canonical_season, r.canonical_episode) for r in records}
    if len(candidates) != 1:
        reasons.append('NUMBERING_CONFLICT')
    if any(type(r.observed_at) is not int or r.observed_at <= 0 or
           r.observed_at > now or now-r.observed_at > max_age for r in records):
        reasons.append('STALE_OR_FUTURE_RECORD')
    if any(not r.authenticated_transport or not r.source_attested for r in records):
        reasons.append('SOURCE_AUTHENTICITY_NOT_ESTABLISHED')
    # Even if all fixture booleans are True, the adapter and identity provenance
    # are not independently authenticated by this function. Fail closed.
    if not reasons:
        reasons.append('PRODUCTION_TRUST_GATE_NOT_IMPLEMENTED')
    return ProvenanceDecision('BLOCKED', tuple(reasons),
                              next(iter(candidates)) if len(candidates) == 1 else None)


def approve_automatically(*args, **kwargs):
    raise ProvenanceError('AUTOMATIC_APPROVAL_DISABLED')


def approve_manually(*args, **kwargs):
    raise ProvenanceError('ADMIN_APPROVAL_REQUIRES_AUTHENTICATED_GATEWAY')
