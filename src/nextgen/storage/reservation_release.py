"""Retire canceled acquisition slots only after proven drained cleanup."""
from src.nextgen.cancellation import CancellationError
from src.nextgen.history import append_job_history


def active(db,operation_id):
    return db.execute("SELECT 1 FROM episode_reservations r JOIN job_operation_members m ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE' LIMIT 1",(operation_id,)).fetchone() is not None


def validate_releasable(db,operation_id):
    if db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id=? AND j.state='RUNNING' LIMIT 1",(operation_id,)).fetchone():raise CancellationError()
    for (evaluation,) in db.execute("SELECT r.evaluation_job_id FROM episode_reservations r JOIN job_operation_members m ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE'",(operation_id,)):
        if db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id<>? AND j.kind IN ('RESERVE_EPISODE','PREPARE_ACQUISITION') AND json_extract(j.payload_json,'$.evaluation_job_id')=? LIMIT 1",(operation_id,evaluation)).fetchone():raise CancellationError()


def release_cancelled(db,operation_id,job_id,now,*,component):
    """Caller holds exclusive operation drain protection and its transaction."""
    if not db.in_transaction:raise CancellationError()
    if db.execute('SELECT state,cleanup_state FROM job_operations WHERE operation_id=?',
                  (operation_id,)).fetchone()!=('CANCELED','COMPLETE'):raise CancellationError()
    validate_releasable(db,operation_id)
    if db.execute("SELECT 1 FROM staging_publications s JOIN job_operation_members m ON m.job_id=s.job_id WHERE m.operation_id=? AND s.state='PUBLISHED' LIMIT 1",(operation_id,)).fetchone():raise CancellationError()
    rows=db.execute("SELECT r.reservation_id,r.evaluation_job_id FROM episode_reservations r JOIN job_operation_members m ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE'",(operation_id,)).fetchall()
    for reservation,evaluation in rows:
        # A historical, separately scoped consumer is still a consumer. Do not
        # free a slot beneath it, even when it is itself stopped or canceled.
        if db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id<>? AND j.kind IN ('RESERVE_EPISODE','PREPARE_ACQUISITION') AND json_extract(j.payload_json,'$.evaluation_job_id')=? LIMIT 1",(operation_id,evaluation)).fetchone():raise CancellationError()
        plans=db.execute('SELECT p.plan_id,p.job_id,m.operation_id FROM acquisition_plans p JOIN job_operation_members m ON m.job_id=p.job_id WHERE p.reservation_id=?',(reservation,)).fetchall()
        for plan,preparation,scope in plans:
            if scope!=operation_id:raise CancellationError()
            if db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id<>? AND json_extract(j.payload_json,'$.preparation_job_id')=? LIMIT 1",(operation_id,preparation)).fetchone():raise CancellationError()
            submission=db.execute('SELECT 1 FROM torrent_submissions WHERE plan_id=?',(plan,)).fetchone()
            if submission and db.execute('SELECT phase FROM cancellation_cleanup WHERE plan_id=?',(plan,)).fetchone()!=('COMPLETE',):raise CancellationError()
            db.execute("UPDATE acquisition_plans SET state='RELEASED' WHERE plan_id=? AND state='PREPARED'",(plan,))
        db.execute("UPDATE episode_reservations SET state='RELEASED',ended_at_ms=?,ended_by_job_id=? WHERE reservation_id=? AND state='ACTIVE'",(now,job_id,reservation))
    if not rows:return ()
    return (append_job_history(db,job_id=job_id,event_code='EPISODE_RESERVATIONS_RELEASED',
        reason_code='CANCELED_RESERVATIONS_RELEASED',component=component,occurred_at_ms=now),)
