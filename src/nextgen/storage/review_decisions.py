"""Explicit rejected-anime decisions and selected staging cleanup."""
import json
import os

from src.nextgen.acquisition.cleanup import directory, parent
from src.nextgen.acquisition.metadata import AcquisitionConflict
from src.nextgen.acquisition.media import signature
from src.nextgen.staging import StagingReview, disjoint


class AnimeRejected(AcquisitionConflict):
    reason_code='ANIME_REJECTED'
    def __init__(self):ValueError.__init__(self,'This anime was rejected; automatic acquisition is stopped.')


def require_allowed(db,anidb_id):
    if db.execute("SELECT 1 FROM anime_review_decisions WHERE anidb_id=? AND decision='REJECT'",(anidb_id,)).fetchone():raise AnimeRejected()


def staged(db,operation_id):
    rows=db.execute("SELECT r.anidb_id,s.plan_id,s.manifest_json,s.receipts_json FROM staging_publications s "
        "JOIN acquisition_plans p USING(plan_id) JOIN episode_reservations r USING(reservation_id) "
        "JOIN job_operation_members m ON m.job_id=s.job_id WHERE m.operation_id=? AND s.state='PUBLISHED'",
        (operation_id,)).fetchall()
    if len(rows)!=1:raise StagingReview()
    return rows[0]


def remove_selected(manifest,receipts,guard,keep_root):
    """Delete only this decision's video and episode NFO; leave series metadata."""
    plan=json.loads(manifest);proofs=json.loads(receipts)
    disjoint(plan['root'],(keep_root,))
    entries=plan['entries']
    # Preflight the entire proven publication before the first unlink.
    # zip() alone silently truncates missing or extra receipts.
    if (type(entries) is not list or type(proofs) is not list
            or not entries or len(entries)!=len(proofs)):
        raise StagingReview()
    for entry,proof in zip(entries,proofs):
        if (type(entry) is not dict or type(proof) is not dict
                or entry.get('role') not in ('media','episode','series')
                or entry.get('role')!=proof.get('role')
                or entry.get('path')!=proof.get('path')):
            raise StagingReview()
    for entry,proof in zip(entries,proofs):
        if entry['role']=='series':continue
        guard()
        with directory(plan['root']) as root:
            if [os.fstat(root).st_dev,os.fstat(root).st_ino]!=plan['root_identity']:raise StagingReview()
            with parent(root,entry['path']) as (folder,name):
                if [os.fstat(folder).st_dev,os.fstat(folder).st_ino]!=proof['root']:raise StagingReview()
                try:info=signature(os.stat(name,dir_fd=folder,follow_symlinks=False))
                except FileNotFoundError:
                    os.fsync(folder);continue
                if list(info)!=proof['file']:raise StagingReview()
                guard()
                if signature(os.stat(name,dir_fd=folder,follow_symlinks=False))!=info:raise StagingReview()
                os.unlink(name,dir_fd=folder);os.fsync(folder)
