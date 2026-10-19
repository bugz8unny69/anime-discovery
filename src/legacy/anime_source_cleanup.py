"""Safe, opt-in source cleanup after qBittorrent removal.

Never remove a source that qBittorrent still owns. The caller must provide
an authenticated qBittorrent client exposing contains_hash and
remove_torrent(hash, delete_files=False). Source files are never deleted
by qBittorrent through this interface.
"""
import hashlib
from pathlib import Path

def _hash(path):
    digest=hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b""):
            digest.update(chunk)
    return digest.hexdigest()

def cleanup_source(db, notification_id, source, qb, *, approved=False):
    """Explicit approval is mandatory. Removes only the exact regular source file."""
    if approved is not True:
        raise PermissionError("Source cleanup requires explicit authorization")
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    row=db.execute("""SELECT infohash,staged_path,sha256 FROM torrent_recovery_records
                      WHERE notification_id=?""",(notification_id,)).fetchone()
    if row is None:
        raise ValueError("No durable recovery record")
    infohash,staged_path,expected=row
    source=Path(source)
    staged=Path(staged_path)
    if source.is_symlink() or staged.is_symlink() or not source.is_file() or not staged.is_file():
        raise ValueError("Missing or unsafe source or staged file")
    source_stat=source.stat()
    staged_stat=staged.stat()
    if source_stat.st_nlink!=1 or staged_stat.st_nlink!=1:
        raise ValueError("Hardlinked media requires manual cleanup")
    if source.resolve()==staged.resolve() or _hash(source)!=expected or _hash(staged)!=expected:
        raise ValueError("Media fingerprint mismatch")
    # No delete_files=True: the application alone owns the final unlink.
    if qb.contains_hash(infohash):
        qb.remove_torrent(infohash,delete_files=False)
    if qb.contains_hash(infohash):
        raise RuntimeError("qBittorrent still owns the torrent")
    # Recheck source immediately before deletion.
    current=source.lstat()
    if (source.is_symlink() or current.st_ino!=source_stat.st_ino
            or current.st_dev!=source_stat.st_dev or current.st_nlink!=1
            or _hash(source)!=expected):
        raise ValueError("Source changed during cleanup")
    # Explicit opt-in only. Path-race protection is not complete: do not
    # wire this routine into unattended daemon handlers yet.
    source.unlink()
    return {"source_removed":True,"infohash":infohash,"staged_path":str(staged)}
