"""Conservative media-completion verification.

A torrent being present is not proof of a finished, safe video. The caller
provides a qBittorrent snapshot and a known download root.
"""
from pathlib import Path

VIDEO_SUFFIXES={".mkv",".mp4",".m4v",".avi"}

def verified_media(torrent, download_root):
    if not isinstance(torrent,dict):
        raise ValueError("Missing torrent snapshot")
    if torrent.get("progress")!=1 or torrent.get("state") not in ("uploading","stalledUP","pausedUP","queuedUP","forcedUP","checkingUP"):
        raise ValueError("Torrent is not fully downloaded")
    root=Path(download_root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Download root missing")
    files=torrent.get("files")
    if not isinstance(files,list) or len(files)!=1:
        raise ValueError("Requires exactly one unambiguous media file")
    entry=files[0]
    if not isinstance(entry,dict) or entry.get("progress")!=1:
        raise ValueError("File is not complete")
    name=entry.get("name")
    if not isinstance(name,str) or not name or Path(name).is_absolute():
        raise ValueError("Unsafe relative file name")
    candidate=root/name
    if candidate.is_symlink() or not candidate.is_file():
        raise ValueError("Missing or symlink media")
    path=candidate.resolve(strict=True)
    if not path.is_relative_to(root) or path.suffix.lower() not in VIDEO_SUFFIXES:
        raise ValueError("Media escapes root or has unsupported extension")
    if path.stat().st_size<=0:
        raise ValueError("Empty media file")
    return path
