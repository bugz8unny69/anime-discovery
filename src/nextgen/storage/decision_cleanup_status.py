"""Shared management cleanup status for one episode or a verified batch.

Keep, Reject, and Retry have one operator-facing contract. The underlying
worker owns the single-file or multi-file proof journal; the dashboard and
management actions must not fork into separate recovery algorithms.
"""
from src.nextgen.cancellation import CancellationError
from src.nextgen.messages import DEFAULT_CATALOG

STOPPED_JOBS = ('NEEDS_REVIEW', 'BLOCKED')


def _batch_status(db, decision, *, kept):
    if kept:
        rows = db.execute(
            "SELECT job_id,state,last_reason_code FROM jobs "
            "WHERE kind='CLEANUP_BATCH_KEPT_MEDIA' AND created_by_job_id=? "
            "ORDER BY job_id", (decision,)).fetchall()
    else:
        rows = db.execute(
            "SELECT job_id,state,last_reason_code FROM jobs "
            "WHERE kind='CLEANUP_BATCH_DOWNLOAD' "
            "AND json_extract(payload_json,'$.decision_job_id')=? "
            "ORDER BY job_id", (decision,)).fetchall()
    if not rows:
        return None
    if len(rows) != 1:
        raise CancellationError()
    job, state, reason = rows[0]
    if kept:
        phase = db.execute(
            'SELECT phase FROM batch_keep_cleanup '
            'WHERE job_id=? AND decision_job_id=?', (job, decision)).fetchone()
        completed_reason = 'POST_KEEP_CLEANUP_COMPLETE'
    else:
        phase = db.execute(
            'SELECT phase FROM batch_download_cleanup '
            'WHERE decision_job_id=?', (decision,)).fetchone()
        completed_reason = 'DECISION_DOWNLOAD_CLEANUP_COMPLETE'
    completed = state == 'DONE' and phase == ('COMPLETE',)
    return {
        'job_id': job, 'state': state,
        'status': DEFAULT_CATALOG.job_status(state),
        'completed': completed,
        'completion': DEFAULT_CATALOG.reason(completed_reason) if completed else None,
        'reason': None if reason is None else DEFAULT_CATALOG.reason(reason),
        'status_url': f'/api/v1/jobs/{job}',
    }


def kept_status(db, decision):
    kind = db.execute(
        'SELECT kind FROM jobs WHERE job_id=?', (decision,)).fetchone()
    if kind == ('KEEP_BATCH',):
        return _batch_status(db, decision, kept=True)
    from src.nextgen.post_keep_cleanup import status
    return status(db, decision)


def download_status(db, decision):
    kind = db.execute(
        'SELECT kind FROM jobs WHERE job_id=?', (decision,)).fetchone()
    if kind==('KEEP_BATCH',):
        return _batch_status(db, decision, kept=False)
    from src.nextgen.decision_download_cleanup import status
    return status(db, decision)
