"""Read-only full-file SHA256 and JP+EN audio proof for each selected episode.

Every path is taken from a hash-pinned inventory, not a job payload.
The caller must first prove the expanded transfer is COMPLETE in the
durable journal. These facts do NOT authorize a staging publication.
"""
import hashlib
import os
from pathlib import PurePosixPath

from src.nextgen.acquisition.cleanup import directory, parent
from src.nextgen.acquisition.media import (
    MediaInvalid, MediaUnavailable, VerifiedMedia, cancelled,
    signature, probe, parse_probe,
)
from src.nextgen.storage.batch_submission_journal import BatchSubmissionIntent
from src.nextgen.staging import disjoint, StagingConfiguration


def verify_selected_batch_episode(intent, file_index, transfer_job_id,
                                  transfer_fingerprint, flag, *,
                                  read_probe=probe, protected_roots=()):
    if type(intent) is not BatchSubmissionIntent or type(file_index) is not int:
        raise MediaInvalid()
    if file_index not in {i for _,i in intent.candidate.planned_episodes}:
        raise MediaInvalid()
    if (type(transfer_job_id) is not int or transfer_job_id<=0
            or type(transfer_fingerprint) is not str
            or len(transfer_fingerprint)!=64):
        raise MediaInvalid()
    item=intent.inventory.files[file_index]
    if PurePosixPath(item.path).suffix.lower() not in ('.mkv','.mp4'):
        raise MediaInvalid()
    try:disjoint(intent.options.download_root,protected_roots)
    except StagingConfiguration:raise MediaInvalid() from None
    try:
        cancelled(flag)
        with directory(intent.options.download_root) as root:
            info=os.fstat(root)
            root_signature=(info.st_dev,info.st_ino)
            with parent(root,item.path) as (folder,name):
                fd=os.open(name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,
                           dir_fd=folder)
                try:
                    before=signature(os.fstat(fd))
                    if before[2]!=item.size:raise MediaInvalid()
                    digest=hashlib.sha256()
                    remaining=item.size
                    while remaining>0:
                        cancelled(flag)
                        chunk=os.read(fd,min(1048576,remaining))
                        if not chunk:raise MediaInvalid()
                        digest.update(chunk)
                        remaining-=len(chunk)
                    if os.read(fd,1):raise MediaInvalid()
                    os.lseek(fd,0,os.SEEK_SET)
                    duration,languages=parse_probe(
                        read_probe(fd,flag),PurePosixPath(item.path).suffix.lower())
                    cancelled(flag)
                    if signature(os.fstat(fd))!=before:raise MediaInvalid()
                    with directory(intent.options.download_root) as current:
                        stat=os.fstat(current)
                        if (stat.st_dev,stat.st_ino)!=root_signature:raise MediaInvalid()
                        with parent(current,item.path) as (latest,leaf):
                            if signature(os.stat(leaf,dir_fd=latest,follow_symlinks=False))!=before:
                                raise MediaInvalid()
                    return VerifiedMedia(
                        intent.candidate.reservation_job_id,transfer_job_id,
                        intent.candidate.plan_id,intent.fingerprint,
                        transfer_fingerprint,item.path,root_signature,before,
                        digest.hexdigest(),duration,languages)
                finally:os.close(fd)
    except OSError:
        raise MediaUnavailable() from None
