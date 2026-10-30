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


def _prune_series(manifests,guard):
    """After a whole-series Reject, drop empty season folders, our own
    tvshow.nfo and the then-empty series folder. Never recursive: any file we
    did not write keeps its folders in place."""
    import errno,hashlib
    from pathlib import PurePosixPath
    targets={}
    for manifest in manifests:
        plan=json.loads(manifest)
        for entry in plan['entries']:
            if entry.get('role')=='series':
                targets[(plan['root'],tuple(plan['root_identity']),entry['path'])]=entry['sha256']
    for (root_path,identity,nfo_path),sha in targets.items():
        guard()
        nfo=PurePosixPath(nfo_path)
        if len(nfo.parts)!=2 or nfo.name!='tvshow.nfo':raise StagingReview()
        with directory(root_path) as root:
            if (os.fstat(root).st_dev,os.fstat(root).st_ino)!=identity:raise StagingReview()
            try:series=os.open(nfo.parts[0],os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=root)
            except FileNotFoundError:continue
            try:
                for name in os.listdir(series):
                    if name.startswith('Season '):
                        try:os.rmdir(name,dir_fd=series)
                        except OSError as error:
                            if error.errno not in (errno.ENOTEMPTY,errno.EEXIST,errno.ENOTDIR,errno.ENOENT):raise
                if os.listdir(series)==['tvshow.nfo']:
                    fd=os.open('tvshow.nfo',os.O_RDONLY|os.O_NOFOLLOW|os.O_CLOEXEC,dir_fd=series)
                    try:
                        info=os.fstat(fd)
                        same=(info.st_size<1048576 and hashlib.sha256(os.read(fd,info.st_size+1)).hexdigest()==sha)
                    finally:os.close(fd)
                    if same:
                        guard()
                        os.unlink('tvshow.nfo',dir_fd=series);os.fsync(series)
                if os.listdir(series):continue
            finally:os.close(series)
            try:os.rmdir(nfo.parts[0],dir_fd=root);os.fsync(root)
            except OSError as error:
                if error.errno not in (errno.ENOTEMPTY,errno.EEXIST,errno.ENOENT):raise


def remove_series(publications,guard,keep_root):
    """Series Reject: remove every staged video and episode NFO, then the
    empty Season folders, our tvshow.nfo and the empty series folder."""
    for manifest,receipts in publications:
        remove_selected(manifest,receipts,guard,keep_root)
    _prune_series(tuple(manifest for manifest,_ in publications),guard)
