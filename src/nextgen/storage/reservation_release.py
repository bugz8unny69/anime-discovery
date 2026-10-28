"""Retire canceled acquisition slots only after proven drained cleanup."""
from src.nextgen.cancellation import CancellationError
from src.nextgen.history import job_attempt, append_job_history


def active(db,operation_id):
    single=db.execute(
        "SELECT 1 FROM episode_reservations r JOIN job_operation_members m "
        "ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE' LIMIT 1",
        (operation_id,)).fetchone()
    batch=db.execute(
        "SELECT 1 FROM batch_episode_reservations r JOIN job_operation_members m "
        "ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE' LIMIT 1",
        (operation_id,)).fetchone()
    return single is not None or batch is not None


def validate_releasable(db,operation_id):
    if db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id=? AND j.state='RUNNING' LIMIT 1",(operation_id,)).fetchone():raise CancellationError()
    # A submitted batch retains its reservations until the same operation's
    # one-shot cancellation journal proves the owned torrent/files are cleaned.
    batches=db.execute(
        "SELECT DISTINCT s.plan_id,c.operation_id,c.phase "
        "FROM batch_torrent_submissions s "
        "JOIN batch_episode_reservations r USING(plan_id) "
        "JOIN job_operation_members m ON m.job_id=r.owner_job_id "
        "LEFT JOIN batch_cancellation_cleanup c ON c.plan_id=s.plan_id "
        "WHERE m.operation_id=? AND r.state='ACTIVE'",
        (operation_id,)).fetchall()
    if any((owner,phase)!=(operation_id,'COMPLETE')
           for _,owner,phase in batches):
        raise CancellationError()
    for (evaluation,) in db.execute("SELECT r.evaluation_job_id FROM episode_reservations r JOIN job_operation_members m ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE'",(operation_id,)):
        if db.execute("SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) WHERE m.operation_id<>? AND j.kind IN ('RESERVE_EPISODE','PREPARE_ACQUISITION') AND json_extract(j.payload_json,'$.evaluation_job_id')=? LIMIT 1",(operation_id,evaluation)).fetchone():raise CancellationError()
    for owner,evaluation in db.execute(
            "SELECT r.owner_job_id,p.evaluation_job_id FROM batch_episode_reservations r "
            "JOIN batch_trial_plans p ON p.plan_id=r.plan_id "
            "JOIN job_operation_members m ON m.job_id=r.owner_job_id "
            "WHERE m.operation_id=? AND r.state='ACTIVE'",(operation_id,)):
        if db.execute(
                "SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) "
                "WHERE m.operation_id<>? AND (j.created_by_job_id=? "
                "OR (j.kind IN ('RESERVE_BATCH','PREPARE_BATCH') "
                "AND json_extract(j.payload_json,'$.evaluation_job_id')=?)) LIMIT 1",
                (operation_id,owner,evaluation)).fetchone():
            raise CancellationError()


def release_cancelled(db,operation_id,job_id,now,*,component):
    """Caller holds exclusive operation drain protection and its transaction."""
    if not db.in_transaction:raise CancellationError()
    if db.execute('SELECT state,cleanup_state FROM job_operations WHERE operation_id=?',
                  (operation_id,)).fetchone()!=('CANCELED','COMPLETE'):raise CancellationError()
    validate_releasable(db,operation_id)
    if db.execute("SELECT 1 FROM staging_publications s JOIN job_operation_members m ON m.job_id=s.job_id WHERE m.operation_id=? AND s.state='PUBLISHED' LIMIT 1",(operation_id,)).fetchone():raise CancellationError()
    from src.nextgen.staging_artifacts import batch_copies_cleared
    if not batch_copies_cleared(db,operation_id):
        raise CancellationError()
    rows=db.execute("SELECT r.reservation_id,r.evaluation_job_id FROM episode_reservations r JOIN job_operation_members m ON m.job_id=r.owner_job_id WHERE m.operation_id=? AND r.state='ACTIVE'",(operation_id,)).fetchall()
    woken=()
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
        from src.nextgen.storage.episode_reservations import wake_waiters
        woken+=wake_waiters(db,reservation,now,component=component)
    batch_rows=db.execute(
        "SELECT r.reservation_id,r.owner_job_id FROM batch_episode_reservations r "
        "JOIN job_operation_members m ON m.job_id=r.owner_job_id "
        "WHERE m.operation_id=? AND r.state='ACTIVE'",(operation_id,)).fetchall()
    for reservation,owner in batch_rows:
        if db.execute(
                "SELECT 1 FROM jobs j JOIN job_operation_members m USING(job_id) "
                "WHERE m.operation_id<>? AND j.created_by_job_id=? LIMIT 1",
                (operation_id,owner)).fetchone():
            raise CancellationError()
        db.execute(
            "UPDATE batch_episode_reservations SET state='RELEASED',"
            "ended_at_ms=?,ended_by_job_id=? WHERE reservation_id=? AND state='ACTIVE'",
            (now,job_id,reservation))
    if not rows and not batch_rows:return ()
    return (append_job_history(db,job_id=job_id,event_code='EPISODE_RESERVATIONS_RELEASED',
        reason_code='CANCELED_RESERVATIONS_RELEASED',component=component,occurred_at_ms=now,details={'attempt':job_attempt(db,job_id)}),*woken)
