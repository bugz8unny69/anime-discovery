"""Future staging integration: precise temporary-file receipts, never directory sweeps."""
import os
import re
from src.nextgen.acquisition.cleanup import directory, parent, fingerprint
from src.nextgen.cancellation import CancellationError
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.sqlite import transaction


class BatchStageCleanupRetry(CancellationError):
    """A staging receipt or file needs bounded recovery, not immediate review."""
    reason_code='STAGING_REVIEW'



def _stage_claim(db,claim):
    import time
    row=db.execute('SELECT state,lease_token,attempt_count,lease_expires_at_ms FROM jobs WHERE job_id=?',(claim.job_id,)).fetchone()
    if (not db.in_transaction or claim.kind not in ('STAGE_TRIAL_MEDIA','STAGE_BATCH_EPISODE') or row is None
            or row[:3]!=('RUNNING',claim.token,claim.attempt) or row[3]<=time.time_ns()//1000000):raise CancellationError()
    op=operation(db,claim.job_id)
    if op[1]!='ACTIVE':raise CancellationError()
    return op[0]


def record_temporary(db,claim,root,name):
    """After exclusive temp-file creation, before copying; caller holds operation gate.

    A crash before this receipt is durable leaves an unowned file for review,
    never permission to sweep a folder. Receipt binds directory and file inodes.
    """
    op=_stage_claim(db,claim)
    if type(name) is not str or not re.fullmatch(r'\.ad-[a-f0-9]{32}\.partial',name):raise CancellationError()
    with directory(root) as fd:
        info=os.stat(name,dir_fd=fd,follow_symlinks=False)
        fingerprint(info)
        folder=os.fstat(fd)
        return db.execute('INSERT INTO staging_cleanup_artifacts(operation_id,job_id,root_path,relative_path,root_device,root_inode,'
            "file_device,file_inode,phase) VALUES(?,?,?,?,?,?,?,?,'TEMP')",
            (op,claim.job_id,root,name,folder.st_dev,folder.st_ino,info.st_dev,info.st_ino)).lastrowid


def publication(db,claim,artifact_id,*,confirmed=False):
    """Record intent before rename, confirmed only after verified publication.

    The future staging library owns filesystem publication/proof. This helper
    grants no rename or deletion authority and is not a public API action.
    """
    op=_stage_claim(db,claim)
    if type(confirmed) is not bool:raise CancellationError()
    old,new=('PUBLISH_UNCERTAIN','PUBLISHED') if confirmed else ('TEMP','PUBLISH_UNCERTAIN')
    changed=db.execute('UPDATE staging_cleanup_artifacts SET phase=? WHERE artifact_id=? AND operation_id=? AND job_id=? AND phase=?',
                      (new,artifact_id,op,claim.job_id,old)).rowcount
    if changed!=1:raise CancellationError()


def clean_temporaries(queue,operation_id,*,guard=None):
    """Caller holds exclusive OperationGate. Preserve published/uncertain media."""
    with queue.connection() as db,transaction(db):
        if guard is not None:guard(db)
        rows=db.execute('SELECT artifact_id,root_path,relative_path,root_device,root_inode,file_device,file_inode,phase '
                        'FROM staging_cleanup_artifacts WHERE operation_id=? ORDER BY artifact_id',(operation_id,)).fetchall()
    for aid,root,name,rdev,rino,fdev,fino,phase in rows:
        if phase in ('PUBLISHED','REMOVED'):continue
        if phase=='PUBLISH_UNCERTAIN':raise CancellationError()
        if not re.fullmatch(r'\.ad-[a-f0-9]{32}\.partial',name):raise CancellationError()
        with directory(root) as fd:
            folder=os.fstat(fd)
            if (folder.st_dev,folder.st_ino)!=(rdev,rino):raise CancellationError()
            try:info=os.stat(name,dir_fd=fd,follow_symlinks=False)
            except FileNotFoundError:info=None
            if info is not None:
                fingerprint(info)
                if (info.st_dev,info.st_ino)!=(fdev,fino):raise CancellationError()
                with queue.connection() as db,transaction(db):
                    if guard is not None:guard(db)
                    db.execute("UPDATE staging_cleanup_artifacts SET phase='REMOVE_UNCERTAIN' WHERE artifact_id=?",(aid,))
                fresh=os.stat(name,dir_fd=fd,follow_symlinks=False)
                if fingerprint(fresh)!=fingerprint(info):raise CancellationError()
                if guard is not None:guard()
                os.unlink(name,dir_fd=fd);os.fsync(fd)
        with queue.connection() as db,transaction(db):
            if guard is not None:guard(db)
            db.execute("UPDATE staging_cleanup_artifacts SET phase='REMOVED' WHERE artifact_id=?",(aid,))

def batch_copies(db, operation_id):
    """Validate every published batch file against its existing staging journal.

    All assertions happen before any unlink. Planned, uncertain publications
    lacking a finished proof are not granted deletion authority.
    """
    import json
    from pathlib import PurePosixPath
    rows=db.execute(
        "SELECT p.job_id,p.manifest_json,p.receipts_json,p.state "
        "FROM batch_staging_publications p "
        "JOIN job_operation_members m ON m.job_id=p.job_id "
        "WHERE m.operation_id=? ORDER BY p.plan_id,p.file_index",
        (operation_id,)).fetchall()
    if len(rows)>1000:raise CancellationError()
    published=[]
    referenced=set()
    for job,manifest,receipts,state in rows:
        if state=='PLANNED':
            # The publisher may have renamed a file before its final commit.
            # Without the full publication receipt, do not guess what to delete.
            if db.execute(
                "SELECT 1 FROM staging_cleanup_artifacts "
                "WHERE operation_id=? AND job_id=? "
                "AND phase IN ('PUBLISH_UNCERTAIN','PUBLISHED') LIMIT 1",
                (operation_id,job)).fetchone():
                raise CancellationError()
            continue
        if state!='PUBLISHED':raise CancellationError()
        try:
            plan=json.loads(manifest)
            proofs=json.loads(receipts)
            entries=plan['entries']
            if (plan.get('transfer')!='COPY'
                    or type(entries) is not list or type(proofs) is not list
                    or len(entries)!=3 or len(proofs)!=3
                    or {entry['role'] for entry in entries}!=
                       {'media','episode','series'}):
                raise CancellationError()
            removable=[]
            for entry,proof in zip(entries,proofs):
                if (entry['role']!=proof['role']
                        or entry['path']!=proof['path']
                        or proof.get('hash_checked') is not True):
                    raise CancellationError()
                artifact=proof.get('artifact')
                if artifact is None:
                    if entry['role']!='series':raise CancellationError()
                    continue
                if type(artifact) is not int or artifact<=0 or artifact in referenced:
                    raise CancellationError()
                referenced.add(artifact)
                source=db.execute(
                    "SELECT operation_id,job_id,root_path,relative_path,"
                    "root_device,root_inode,file_device,file_inode,phase "
                    "FROM staging_cleanup_artifacts WHERE artifact_id=?",
                    (artifact,)).fetchone()
                relative=PurePosixPath(entry['path'])
                expected=(operation_id,job,
                    plan['root']+'/'+str(relative.parent),entry['temporary'],
                    *proof['root'],*proof['file'][:2])
                if source is None or source[:8]!=expected:
                    raise CancellationError()
                if entry['role']!='series':
                    if source[8] not in ('PUBLISHED','REMOVED'):
                        raise CancellationError()
                    removable.append((artifact,source[8]))
                elif source[8]!='PUBLISHED':
                    raise CancellationError()
            if len(removable)!=2:raise CancellationError()
            published.append((manifest,receipts,tuple(removable)))
        except (ValueError,KeyError,TypeError,IndexError):
            raise CancellationError() from None

    # No published inode may be left without a committed staging receipt.
    # This catches a crash between rename/confirm and final publish.
    stranded=db.execute(
        "SELECT a.artifact_id FROM staging_cleanup_artifacts a "
        "JOIN job_operation_members m ON m.job_id=a.job_id "
        "WHERE m.operation_id=? AND a.phase='PUBLISHED' "
        "AND a.job_id IN (SELECT job_id FROM batch_staging_publications)",
        (operation_id,)).fetchall()
    if any((artifact not in referenced) for (artifact,) in stranded):
        raise CancellationError()
    return tuple(published)


def clean_published_batch(queue,operation_id,*,guard,keep_root,remove=None):
    """Idempotently clean only verified batch video/episode copies on Cancel.

    The existing PUBLISHED -> REMOVED artifact receipt is durable; a crash
    after unlink but before the receipt commits safely reconciles on retry.
    Shared series NFOs intentionally remain in place.
    """
    from src.nextgen.storage.review_decisions import remove_selected
    from src.nextgen.staging import StagingReview
    if remove is None:remove=remove_selected
    with queue.connection() as db,transaction(db):
        guard(db)
        try:items=batch_copies(db,operation_id)
        except CancellationError:raise BatchStageCleanupRetry() from None
    for manifest,receipts,artifacts in items:
        guard()
        try:remove(manifest,receipts,guard,keep_root)
        except (StagingReview,OSError):
            raise BatchStageCleanupRetry() from None
        with queue.connection() as db,transaction(db):
            guard(db)
            # Revalidate all publication and inode receipts before completing.
            try:current=batch_copies(db,operation_id)
            except CancellationError:raise BatchStageCleanupRetry() from None
            if not any(m==manifest and p==receipts and a==artifacts
                       for m,p,a in current):
                raise BatchStageCleanupRetry()
            for artifact,phase in artifacts:
                if phase=='REMOVED':continue
                updated=db.execute(
                    "UPDATE staging_cleanup_artifacts SET phase='REMOVED' "
                    "WHERE artifact_id=? AND operation_id=? AND phase='PUBLISHED'",
                    (artifact,operation_id)).rowcount
                if updated!=1:raise BatchStageCleanupRetry()


def batch_copies_cleared(db,operation_id):
    return all(all(phase=='REMOVED' for _,phase in artifacts)
               for _,_,artifacts in batch_copies(db,operation_id))
