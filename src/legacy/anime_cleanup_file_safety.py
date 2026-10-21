"""Conservative qB-managed download-file deletion preflight.

No filesystem mutation here. If ANY torrent file is ambiguous, shared, linked,
symlinked, outside dedicated download storage, or still downloading, refuse
qB deleteFiles=True. This never authorizes removal of staged/library media.
"""
import os
import stat
from pathlib import Path, PurePosixPath

_STOPPED=frozenset({"pausedUP","pausedDL","stoppedUP","stoppedDL"})
_MAX_FILES=500
_MAX_OTHER_TORRENTS=500

def _within(path,root):
    try:
        path.relative_to(root)
        return path != root
    except ValueError:
        return False

def _existing_download_path(root,name):
    if not isinstance(name,str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("Untrusted qBittorrent file name")
    relative=PurePosixPath(name)
    if relative.is_absolute() or any(part in (".","..","") for part in relative.parts):
        raise ValueError("Torrent path traversal blocked")
    path=root.joinpath(*relative.parts)
    if not _within(path,root):
        raise ValueError("Torrent path outside save directory")
    cursor=root
    for part in relative.parts[:-1]:
        cursor=cursor/part
        if cursor.is_symlink():
            raise ValueError("Symlinked download directory")
    if path.is_symlink() or not path.is_file():
        raise ValueError("Unverified download file")
    info=path.lstat()
    if not stat.S_ISREG(info.st_mode) or info.st_nlink!=1:
        raise ValueError("Nonregular or hardlinked torrent data")
    return path,info

def preflight(qb,infohash,*,download_root,trial_root,sonarr_root=None):
    """Return verified per-file list and byte estimate, never delete files."""
    root=Path(download_root)
    trial=Path(trial_root)
    if (not root.is_dir() or root.is_symlink() or
        not trial.is_dir() or trial.is_symlink()):
        raise ValueError("Configured storage roots not safely accessible")
    root=root.resolve(strict=True)
    trial=trial.resolve(strict=True)
    if root==trial or _within(root,trial) or _within(trial,root):
        raise ValueError("Download and staging storage overlap")
    if sonarr_root:
        other=Path(sonarr_root)
        if other.exists():
            other=other.resolve(strict=True)
            if root==other or _within(root,other) or _within(other,root):
                raise ValueError("Downloads overlap Sonarr-managed storage")
    detail=qb.torrent_details(infohash)
    if not detail or detail.get("hash","").lower()!=infohash:
        raise ValueError("Exact torrent details unavailable")
    if detail.get("state") not in _STOPPED:
        raise ValueError("Stop the torrent before deleting its download files")
    save=detail.get("save_path")
    if not isinstance(save,str) or not save.startswith("/"):
        raise ValueError("Untrusted torrent save path")
    path_root=Path(save)
    if not path_root.is_dir() or path_root.is_symlink():
        raise ValueError("Unsafe torrent save path")
    path_root=path_root.resolve(strict=True)
    if not (_within(path_root,root) or path_root==root):
        raise ValueError("Torrent save path outside download root")
    items=qb.torrent_files(infohash)
    if not items or len(items)>_MAX_FILES:
        raise ValueError("Missing or oversized torrent file manifest")
    candidates={}
    for item in items:
        if not isinstance(item,dict):
            raise ValueError("Malformed torrent file manifest")
        target,info=_existing_download_path(path_root,item.get("name"))
        declared=item.get("size")
        if type(declared) is not int or declared<0 or info.st_size>declared:
            raise ValueError("Downloaded file size conflicts with qB manifest")
        if not _within(target.resolve(strict=True),root):
            raise ValueError("Download resolves outside configured storage")
        if target in candidates:
            raise ValueError("Duplicate torrent target")
        candidates[target]=(info.st_dev,info.st_ino,info.st_size,info.st_mtime_ns)
    others=qb.torrent_inventory()
    if not isinstance(others,list) or len(others)>_MAX_OTHER_TORRENTS:
        raise ValueError("Unable to rule out shared qBittorrent downloads")
    for other in others:
        if not isinstance(other,dict):
            raise ValueError("Malformed qBittorrent inventory")
        other_hash=other.get("hash")
        if not isinstance(other_hash,str):
            raise ValueError("Missing inventory hash")
        if other_hash.lower()==infohash:
            continue
        other_save=other.get("save_path")
        if not isinstance(other_save,str) or not other_save.startswith("/"):
            raise ValueError("Shared download inventory incomplete")
        for entry in qb.torrent_files(other_hash.lower()):
            if not isinstance(entry,dict) or not isinstance(entry.get("name"),str):
                raise ValueError("Shared torrent manifest unavailable")
            name=PurePosixPath(entry["name"])
            if name.is_absolute() or ".." in name.parts:
                raise ValueError("Unsafe shared torrent path")
            candidate=Path(other_save).joinpath(*name.parts).resolve(strict=False)
            if candidate in candidates:
                raise ValueError("Torrent file shared with another torrent")
    # Reinspect each file directly before returning the plan.
    for path,expected in candidates.items():
        current=path.lstat()
        observed=(current.st_dev,current.st_ino,current.st_size,current.st_mtime_ns)
        if path.is_symlink() or observed!=expected:
            raise ValueError("Download changed during cleanup preview")
    return {"files":sorted(str(p) for p in candidates),
            "bytes":sum(value[2] for value in candidates.values())}
