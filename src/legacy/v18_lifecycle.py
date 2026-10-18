"""V18 lifecycle policy: no qB, filesystem, or Sonarr mutations in this module."""
from dataclasses import dataclass

@dataclass(frozen=True)
class Trial:
    infohash: str
    verification: str
    confidence: int
    blocked: bool = False
    state: str = 'DISCOVERED'
    completed_data_available: bool = False
    ownership_proven: bool = False

class LifecycleError(ValueError): pass

def transition(t: Trial, action: str) -> str:
    if action == 'AUTO_APPROVE':
        if t.blocked or t.verification != 'AUTO_VERIFIED_CANDIDATE' or t.confidence < 90 or t.state != 'DISCOVERED':
            raise LifecycleError('not eligible for automatic approval')
        return 'APPROVED_PAUSED'
    if action == 'STAGE_TRIAL':
        if t.state != 'APPROVED_PAUSED' or not t.completed_data_available:
            raise LifecycleError('cannot stage without existing completed data')
        return 'TRIAL_READY'
    if action == 'KEEP':
        if t.state != 'TRIAL_READY': raise LifecycleError('trial not ready')
        return 'PROMOTION_REQUESTED'
    if action == 'REJECT':
        if t.state != 'TRIAL_READY': raise LifecycleError('trial not ready')
        return 'REJECTED_BLOCKED'
    if action == 'WEBHOOK_REPLAY':
        if t.blocked or t.state == 'REJECTED_BLOCKED': return 'REJECTED_BLOCKED'
        return t.state
    if action == 'RESTORE_FOR_TRIAL':
        if t.state != 'REJECTED_BLOCKED' or not t.completed_data_available:
            raise LifecycleError('restore requires rejected release and existing completed data')
        return 'RESTORE_REQUESTED_PAUSED'
    if action == 'DELETE_TRIAL_COPY':
        if t.state != 'REJECTED_BLOCKED' or not t.ownership_proven:
            raise LifecycleError('refuse deletion without ownership proof')
        return 'TRIAL_COPY_REMOVAL_AUTHORIZED'
    raise LifecycleError('unknown action')
