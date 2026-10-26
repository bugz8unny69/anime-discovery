"""Append-only per-episode media facts fenced to a completed owned pack.

No database row is a staging permit. Source files and their inodes must
still be rechecked immediately before the eventual staging publication.
"""
from src.nextgen.acquisition.media import VerifiedMedia, MediaInvalid
from src.nextgen.history import integer


def persist_batch_file_proof(db,claim,media,*,file_index,tvdb_episode,now_ms):
    if not db.in_transaction or type(media) is not VerifiedMedia:
        raise MediaInvalid()
    integer(file_index)
    integer(tvdb_episode,positive=True)
    integer(now_ms)
    lease=db.execute(
        "SELECT state,kind,attempt_count,lease_token,lease_expires_at_ms,event_id "
        "FROM jobs WHERE job_id=?",(claim.job_id,)).fetchone()
    if (lease is None or lease[:4]!=('RUNNING','VERIFY_BATCH_FILES',claim.attempt,claim.token)
            or lease[4] is None or lease[4]<=now_ms or lease[5]!=claim.event_id):
        raise MediaInvalid()
    row=db.execute(
        "SELECT f.file_path,f.file_size_bytes,p.plan_id,"
        "u.phase,u.unlock_job_id,s.fingerprint "
        "FROM batch_trial_files t "
        "JOIN batch_trial_plans p ON p.plan_id=t.plan_id "
        "JOIN batch_verified_files f ON f.batch_id=p.batch_id "
        "AND f.file_index=t.file_index AND f.tvdb_episode=t.tvdb_episode "
        "JOIN batch_torrent_unlocks u ON u.plan_id=p.plan_id "
        "JOIN batch_torrent_submissions s ON s.plan_id=p.plan_id "
        "WHERE t.plan_id=? AND t.file_index=? AND t.tvdb_episode=?",
        (media.plan_id,file_index,tvdb_episode)).fetchone()
    if (row is None or row[0]!=media.relative_path
            or row[1]!=media.file_signature[2]
            or row[3]!='COMPLETE'
            or row[5]!=media.submission_fingerprint):
        raise MediaInvalid()
    parent=db.execute(
        "SELECT j.created_by_job_id,op.state "
        "FROM jobs j JOIN job_operation_members jm ON jm.job_id=j.job_id "
        "JOIN job_operations op ON op.operation_id=jm.operation_id "
        "JOIN job_operation_members um ON um.job_id=? AND um.operation_id=jm.operation_id "
        "WHERE j.job_id=? AND j.kind='VERIFY_BATCH_FILES' ",
        (row[4],claim.job_id)).fetchone()
    if parent!=(row[4],'ACTIVE'):raise MediaInvalid()
    if media.languages!=('eng','jpn'):raise MediaInvalid()
    encoded=media.json()
    if len(encoded.encode('utf-8'))>65536:raise MediaInvalid()
    prior=db.execute(
        "SELECT evidence_json FROM batch_verified_media_files "
        "WHERE plan_id=? AND file_index=?",
        (media.plan_id,file_index)).fetchone()
    if prior is not None:
        if prior[0]!=encoded:raise MediaInvalid()
        return False
    db.execute(
        "INSERT INTO batch_verified_media_files"
        "(plan_id,file_index,tvdb_episode,evidence_json,verified_at_ms) "
        "VALUES(?,?,?,?,?)",(media.plan_id,file_index,tvdb_episode,encoded,now_ms))
    return True
