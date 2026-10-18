"""Phase 2X-Q: fail-closed offline approval gateway.

Only a trusted administrator-side process may invoke this gateway. It does not
authenticate users, retrieve provider data, or expose HTTP routes. No live DB use.
"""
from collections.abc import Mapping
from transactional_approval import approve_revision
from trusted_evidence import preflight

class GatewayError(ValueError):
    pass

def approve_pinned_revision(db, *, revision_id, envelope, admin_key, now):
    """Require evidence preflight inside the SAME write transaction as approval.

    Do not expose transactional_approval.approve_revision directly in production:
    its optional trusted_preflight parameter permits legacy fixture-only approvals.
    """
    if type(revision_id) is not int or revision_id <= 0:
        raise GatewayError('INVALID_REVISION')
    if type(now) is not int or now <= 0:
        raise GatewayError('INVALID_TIME')
    if not isinstance(envelope, Mapping):
        raise GatewayError('INVALID_ENVELOPE')
    if type(admin_key) is not bytes or len(admin_key) < 32:
        raise GatewayError('INVALID_ADMIN_KEY')
    # Intentionally no caller-supplied candidate, digest, preflight or trust flag.
    return approve_revision(db, revision_id=revision_id, envelope=dict(envelope),
                            key=admin_key, now=now, trusted_preflight=preflight)
