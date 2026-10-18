"""Fail-closed building blocks for a future controller deployment.

No live database, network, torrent, or service operations are performed here.
"""
import hashlib
import os
import stat
from pathlib import Path


class BoundaryError(ValueError):
    pass


class FileFingerprint(dict):
    """Fingerprint with a retained descriptor to prevent inode reuse.

    Call close() when finished; __del__ is a fallback. Not serializable as
    durable evidence: revalidation after process restart must fail closed.
    """
    def __init__(self, values, fd):
        super().__init__(values)
        self._fd = fd

    def close(self):
        if self._fd is not None:
            os.close(self._fd)
            self._fd = None

    def __del__(self):
        self.close()


def fingerprint_regular_file(path, root):
    """Open without following final symlink; reject escapes and changing files.

    Hash via the opened descriptor, not a second pathname lookup. A caller must
    compare this fingerprint to a freshly verified media probe before committing.
    """
    root = Path(root).resolve(strict=True)
    path = Path(path)
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root) or resolved == root:
        raise BoundaryError('outside allowed root')
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
            raise BoundaryError('not a single-linked regular file')
        h = hashlib.sha256()
        with os.fdopen(os.dup(fd), 'rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                h.update(block)
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(before, f) != getattr(after, f) for f in fields):
            raise BoundaryError('file changed while hashing')
        if path.resolve(strict=True) != resolved:
            raise BoundaryError('path changed while hashing')
        current = path.lstat()
        if any(getattr(current, f) != getattr(after, f) for f in fields):
            raise BoundaryError('file replaced while hashing')
        lease = os.dup(fd)
        return FileFingerprint({'path': str(resolved), 'dev': after.st_dev, 'ino': after.st_ino,
                'size': after.st_size, 'mtime_ns': after.st_mtime_ns,
                'ctime_ns': after.st_ctime_ns, 'sha256': h.hexdigest()}, lease)
    finally:
        os.close(fd)


def verify_unchanged(path, root, expected):
    """Rehash before commit; false if the file has changed or is unsafe."""
    if not isinstance(expected, FileFingerprint) or expected._fd is None:
        return False
    try:
        held = os.fstat(expected._fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if held.st_nlink != 1 or any(
            getattr(held, field) != expected[key] for field, key in zip(
                fields, ('dev', 'ino', 'size', 'mtime_ns', 'ctime_ns'))
        ):
            return False
        current = fingerprint_regular_file(path, root)
        try:
            return current == expected and os.path.samestat(
                os.fstat(expected._fd), os.fstat(current._fd))
        finally:
            current.close()
    except (OSError, BoundaryError):
        return False


def mapping_evidence_gate(*, series_id, season, episode, providers):
    """Require two independent verified canonical-numbering sources.

    This is a *gate*, not a provider authenticator. Provider adapters must be
    independently audited before setting authenticated=True. Self-declared
    booleans from API requests MUST NOT be forwarded to this function.
    """
    if season != 1 or not 1 <= episode <= 6 or not isinstance(providers, (list, tuple)):
        return {'approved': False, 'reason': 'INVALID_MAPPING'}
    valid = []
    for p in providers:
        if not isinstance(p, dict):
            continue
        if (p.get('authenticated') is True and p.get('canonical') is True
            and p.get('series_id') == series_id and p.get('season') == season
            and p.get('episode') == episode and isinstance(p.get('authority'), str)
            and p['authority'] and isinstance(p.get('record_digest'), str)
            and len(p['record_digest']) == 64
            and all(c in '0123456789abcdef' for c in p['record_digest'])):
            valid.append(p)
    authorities = {p['authority'] for p in valid}
    return {'approved': len(authorities) >= 2,
            'reason': 'TWO_INDEPENDENT_AUTHORITIES' if len(authorities) >= 2 else 'INSUFFICIENT_AUTHENTICATED_PROVENANCE'}


def guarded_cancel_decision(*, job, attempt, inventory, current_generation):
    """Preflight only. No qB call; no claim of race-free execution."""
    required = ('series_id', 'attempt_id', 'torrent_hash', 'generation')
    if any(k not in job for k in required) or not isinstance(attempt, dict):
        return False
    if job.get('delete_files', 0) != 0 or job['generation'] != current_generation:
        return False
    if (attempt.get('id') != job['attempt_id'] or attempt.get('series_id') != job['series_id']
        or attempt.get('generation') != job['generation']
        or attempt.get('torrent_hash', '').lower() != job['torrent_hash'].lower()
        or attempt.get('status') not in ('QUEUED', 'DOWNLOADING', 'STALLED')):
        return False
    matches = [i for i in inventory if i.get('hash', '').lower() == job['torrent_hash'].lower()]
    return len(matches) == 1 and matches[0].get('generation') == job['generation']


def verified_episode1_snapshot(controller, db, series_id, attempt_id):
    """Real controller media verification bracketed by descriptor-backed hashes.

    Returns evidence only if file identity survives ffprobe and stability checks.
    Callers must revalidate the evidence before transaction commit. This does
    not eliminate every possible external replacement race on network mounts.
    """
    row = db.execute('''SELECT st.status, st.staged_path, st.imported_path,
        a.status AS attempt_status FROM staged_episodes st
        JOIN download_attempts a ON a.id=st.attempt_id
        AND a.series_id=st.series_id AND a.season=st.season AND a.episode=st.episode
        WHERE st.series_id=? AND st.season=1 AND st.episode=1 AND st.attempt_id=?''',
        (series_id, attempt_id)).fetchone()
    if not row or row['attempt_status'] != 'COMPLETED':
        return None
    if row['status'] == 'STAGED':
        path = row['staged_path']
        root = controller.TRIAL_STAGING_ROOT
        check = controller.staged_file_check
    elif row['status'] == 'IMPORTED':
        path = row['imported_path']
        root = controller.TRIAL_LIBRARY_ROOT
        check = controller.imported_file_check
    else:
        return None
    # Hold the original inode open throughout the pathname-based probes.
    # Otherwise an unlink/recreate can reuse an inode and identical timestamps.
    fd = None
    try:
        before = fingerprint_regular_file(path, root)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) |
                     getattr(os, 'O_NONBLOCK', 0))
        held = os.fstat(fd)
        if not stat.S_ISREG(held.st_mode) or held.st_nlink != 1:
            return None
        if (held.st_dev, held.st_ino, held.st_size, held.st_mtime_ns,
                held.st_ctime_ns) != (before['dev'], before['ino'], before['size'],
                                     before['mtime_ns'], before['ctime_ns']):
            return None
        if check(path, row['attempt_status']).get('verified') is not True:
            return None
        if row['status'] == 'STAGED' and controller.check_file_stability(
                db, series_id, 1, 1, path).get('stable') is not True:
            return None
        current = os.stat(path, follow_symlinks=False)
        after = os.fstat(fd)
        fields = ('st_dev', 'st_ino', 'st_size', 'st_mtime_ns', 'st_ctime_ns')
        if any(getattr(current, field) != getattr(held, field) or
               getattr(after, field) != getattr(held, field)
               for field in fields):
            return None
        if after.st_nlink != 1 or not verify_unchanged(path, root, before):
            return None
        return before
    except (OSError, BoundaryError, TypeError, ValueError):
        return None
    finally:
        if fd is not None:
            os.close(fd)
