"""Bounded normal-submit / poll / pause stage for an owned qBittorrent torrent.

For the future series-verified batch worker. No live worker uses this yet.
A caller must first verify the series identity and torrent's authorization.
The torrent may transfer some pieces before the manifest arrives; this is
intentional. Always stop it before using that manifest to choose wanted files.
"""
import time
import logging
from pathlib import PurePosixPath

from anime_qb_ownership import OWNED, owned_now, ownership
from anime_qb_submission import submit_once

LOG = logging.getLogger("anime_discovery.trial")

STOPPED = frozenset(("pausedDL", "pausedUP", "stoppedDL", "stoppedUP"))


def _validated_manifest(files):
    """Return stable index/name/size inventory or fail closed."""
    if not isinstance(files, list) or not files or len(files) > 10000:
        raise ValueError("Missing or excessive torrent manifest")
    result = []
    for entry in files:
        if not isinstance(entry, dict):
            raise ValueError("Invalid torrent manifest entry")
        index, name, size, priority = (entry.get("index"), entry.get("name"),
                                       entry.get("size"), entry.get("priority"))
        if (type(index) is not int or index < 0 or
                not isinstance(name, str) or not name or len(name) > 2048 or
                name.startswith("/") or "\\" in name or
                any(p in (".", "..", "") for p in name.split("/")) or
                type(size) is not int or size < 0 or
                type(priority) is not int or priority < 0):
            raise ValueError("Unsafe or incomplete torrent manifest entry")
        path = PurePosixPath(name)
        if path.is_absolute() or not path.name:
            raise ValueError("Unsafe torrent file path")
        result.append((index, name, size, priority))
    result.sort()
    if [item[0] for item in result] != list(range(len(result))):
        raise ValueError("Torrent file indices are missing or duplicated")
    return result


def _stop_and_wait(qb, infohash, *, sleep):
    """Stop exact owned torrent; tolerate the asynchronous state transition."""
    try:
        qb.stop_owned_torrent(infohash)
    except RuntimeError as exc:
        if str(exc) != "qBittorrent stop not yet confirmed":
            raise
    for _ in range(10):
        detail = qb.torrent_identity(infohash)
        if detail and detail.get("state") in STOPPED:
            return
        sleep(0.2)
    raise RuntimeError("Torrent did not stop in time; do not change file selection")


def submit_poll_pause(db, infohash, magnet_uri, qb, *, attempts=10, interval=1.0,
                      sleep=time.sleep):
    """Submit once, poll ~once/sec for metadata, then pause and verify files.

    This stage intentionally does not select files, resume an episode,
    or assert that a release's name is a verified canonical series identity.
    A production caller must enforce series verification before invocation.

    A bounded active window avoids letting a metadata-starved torrent run
    indefinitely. On a later deferred retry, only an already proven-owned
    paused torrent *without metadata* may be resumed to obtain its manifest.
    """
    if type(attempts) is not int or not 1 <= attempts <= 120:
        raise ValueError("Invalid metadata polling attempts")
    if type(interval) not in (float, int) or not 0 <= interval <= 10:
        raise ValueError("Invalid polling interval")
    if not callable(sleep) or db.in_transaction:
        raise ValueError("Autocommit and sleeper required")

    submitted = submit_once(db, infohash, magnet_uri, qb)
    if not submitted:
        # The add may have succeeded before qB exposes the hash. Poll briefly
        # and reconcile its existing reservation; never issue another add.
        for check in range(attempts):
            if qb.contains_hash(infohash):
                submitted = submit_once(db, infohash, magnet_uri, qb)
                if submitted:
                    break
            if check + 1 < attempts:
                sleep(interval)
        if not submitted:
            LOG.warning("event=TORRENT_INTAKE_DEFERRED reason=SUBMISSION_NOT_RECONCILED hash=%s",
                        infohash[:12])
            return {"state": "DEFERRED", "reason": "Submission not reconciled"}
    # submit_once may find an externally owned, same-hash torrent: never
    # pause, reprioritize or otherwise control another application's source.
    if ownership(db, infohash) != OWNED or not owned_now(db, infohash, qb):
        LOG.warning("event=TORRENT_INTAKE_REJECTED reason=OWNERSHIP_UNPROVEN hash=%s",
                    infohash[:12])
        return {"state": "NEEDS_REVIEW", "reason": "Torrent ownership not proven"}

    current = qb.torrent_identity(infohash)
    if not current:
        LOG.info("event=TORRENT_INTAKE_DEFERRED reason=TORRENT_NOT_VISIBLE hash=%s", infohash[:12])
        return {"state": "DEFERRED", "reason": "Torrent not yet visible"}
    if current.get("state") in STOPPED and not qb.torrent_files(infohash):
        # The earlier active discovery window timed out; try again without
        # adding another magnet. Adapter enforces no manifest on resume.
        LOG.info("event=TORRENT_METADATA_RETRY reason=INCOMPLETE_MANIFEST hash=%s", infohash[:12])
        qb.resume_owned_metadata(infohash)

    for attempt in range(attempts):
        # Query exact infohash; a healthy qB API returns [] while a magnet
        # is still fetching metadata.
        files = qb.torrent_files(infohash)
        if files:
            _stop_and_wait(qb, infohash, sleep=sleep)
            # Metadata appears atomically in qB, but verify file identities
            # again after stopping to reject races/unstable file inventories.
            before = _validated_manifest(files)
            stopped_files = qb.torrent_files(infohash)
            after = _validated_manifest(stopped_files)
            if before != after:
                LOG.warning("event=TORRENT_INTAKE_REJECTED reason=MANIFEST_CHANGED hash=%s", infohash[:12])
                raise ValueError("Torrent manifest changed during pause")
            if ownership(db, infohash) != OWNED or not owned_now(db, infohash, qb):
                raise PermissionError("Torrent ownership changed during pause")
            LOG.info("event=TORRENT_MANIFEST_READY reason=FILE_LIST_VERIFIED hash=%s file_count=%d",
                     infohash[:12],len(stopped_files))
            return {"state": "MANIFEST_READY", "infohash": infohash.lower(),
                    "files": stopped_files}
        if attempt + 1 < attempts:
            sleep(interval)
    _stop_and_wait(qb, infohash, sleep=sleep)
    LOG.info("event=TORRENT_INTAKE_DEFERRED reason=METADATA_NOT_READY hash=%s",
             infohash[:12])
    return {"state": "DEFERRED", "reason": "Torrent metadata not yet available"}
