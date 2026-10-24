"""Evidence checks for one approved staged episode and its Sonarr library copy.

Read-only file operations: strict no-symlink traversal, exact recorded staged
inode/signature, and SHA-256 equivalence before permanent-import success.
"""
import os
from pathlib import PurePosixPath

from src.nextgen.acquisition.cleanup import directory, parent
from src.nextgen.acquisition.media import signature
from src.nextgen.staging import StagingReview, digest_fd, open_regular


class KeepFileReview(StagingReview):
    reason_code="KEEP_FILE_REVIEW"
    def __init__(self):
        ValueError.__init__(self,"The approved staged file or Sonarr library copy needs review.")


def _absolute(root,relative):
    if (type(root) is not str or type(relative) is not str
            or not root.startswith("/") or root.startswith("//")
            or relative.startswith("/") or any(p in ("..",".") for p in relative.split("/"))
            or not relative or "//" in relative):
        raise KeepFileReview()
    return root.rstrip("/")+"/"+relative


def _read(root, relative, flag, *, root_identity=None, expected_signature=None, expected_size=None):
    try:
        with directory(root) as root_fd:
            info=os.fstat(root_fd)
            if root_identity is not None and [info.st_dev,info.st_ino]!=root_identity:
                raise KeepFileReview()
            with parent(root_fd,relative) as (folder,name):
                fd=open_regular(folder,name)
                try:
                    before=signature(os.fstat(fd))
                    if expected_signature is not None and list(before)!=expected_signature:
                        raise KeepFileReview()
                    size=before[2]
                    if expected_size is not None and size!=expected_size:
                        raise KeepFileReview()
                    digest,after=digest_fd(fd,size,flag)
                    if before!=after:raise KeepFileReview()
                    return digest,list(after)
                finally:os.close(fd)
    except (ValueError,KeyError,FileNotFoundError,NotADirectoryError,PermissionError,OSError):
        raise KeepFileReview() from None


def staged(record,flag):
    """Verify media still matches published inode, size and original digest."""
    approved=record["approval"]
    manifest=approved["manifest"]
    entries=manifest["entries"]
    receipts=approved["receipts"]
    items=[(e,r) for e,r in zip(entries,receipts) if e["role"]=="media"]
    if len(items)!=1:raise KeepFileReview()
    entry,proof=items[0]
    digest,identity=_read(manifest["root"],entry["path"],flag,
                           root_identity=manifest["root_identity"],
                           expected_signature=proof["file"],expected_size=entry["size"])
    if digest!=entry["sha256"] or digest!=proof["sha256"]:
        raise KeepFileReview()
    return {
        "path":_absolute(manifest["root"],entry["path"]),
        "signature":identity,"size":entry["size"],"sha256":digest
    }


def verified_library(record, client, flag, staged_evidence):
    """Verify exact Sonarr episode-file references and copied bytes.

    Called ONLY after Sonarr confirms the recorded ManualImport command done.
    """
    approved=record["approval"]
    identity=approved["identity"]
    series_id=record["sonarr_id"]
    command_id=record["command_id"]
    episodes,files=client.inventory(series_id)
    if not isinstance(episodes,list) or not isinstance(files,list):
        raise KeepFileReview()
    matched=[e for e in episodes if isinstance(e,dict)
             and e.get("seasonNumber")==identity["tvdb_season"]
             and e.get("episodeNumber")==identity["tvdb_episode"]]
    if len(matched)!=1 or type(matched[0].get("id")) is not int:
        raise KeepFileReview()
    episode=matched[0]
    tvdb_ep=episode.get("tvdbId")
    if tvdb_ep is not None and tvdb_ep!=identity["tvdb_episode_id"]:
        raise KeepFileReview()
    if record["selected"] is None or len(record["selected"])!=1:
        raise KeepFileReview()
    selected=record["selected"][0]
    if (selected["episodeIds"]!=[episode["id"]] or selected["seriesId"]!=series_id
            or selected["path"]!=staged_evidence["path"]):
        raise KeepFileReview()
    file_id=episode.get("episodeFileId")
    matched_files=[f for f in files if isinstance(f,dict) and f.get("id")==file_id
                   and f.get("seriesId")==series_id]
    if len(matched_files)!=1 or type(file_id) is not int or file_id<=0:
        raise KeepFileReview()
    dest=matched_files[0].get("path")
    root=record["root"]
    if type(dest) is not str or dest.startswith("//"):
        raise KeepFileReview()
    root_path=PurePosixPath(root);dest_path=PurePosixPath(dest)
    if (not dest_path.is_absolute() or not dest_path.is_relative_to(root_path)
            or dest_path==root_path or str(dest_path)!=dest
            or any(part in ("..",".") for part in dest.split("/"))):
        raise KeepFileReview()
    relative=str(dest_path.relative_to(root_path))
    digest,proof=_read(root,relative,flag,expected_size=staged_evidence["size"])
    if digest!=staged_evidence["sha256"] or proof[:2]==staged_evidence["signature"][:2]:
        raise KeepFileReview()
    return {
        "sonarr_series_id":series_id,"sonarr_episode_id":episode["id"],
        "sonarr_file_id":file_id,"sonarr_command_id":command_id,
        "path":dest,"size":proof[2],"sha256":digest,
        "copy_signature":proof
    }
