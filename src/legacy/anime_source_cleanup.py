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
    if source.resolve()==staged.resolve() or _hash(source)!=expected or _hash(staged)!=expected:
        raise ValueError("Media fingerprint mismatch")
    # No delete_files=True: the application alone owns the final unlink.
    if qb.contains_hash(infohash):
        qb.remove_torrent(infohash,delete_files=False)
    if qb.contains_hash(infohash):
        raise RuntimeError("qBittorrent still owns the torrent")
    # Recheck source immediately before deletion.
    if source.is_symlink() or _hash(source)!=expected:
        raise ValueError("Source changed during cleanup")
    source.unlink()
    return {"source_removed":True,"infohash":infohash,"staged_path":str(staged)}
