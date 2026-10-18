"""Approved-episode acquisition orchestration.

A dispatch claim is necessary but never sufficient. This rechecks canonical
identity, rejection and episode verification before invoking the idempotent
qBittorrent submission boundary. No service configuration is changed.
"""
from anime_acquisition_gate import approved_dispatch
from anime_qb_submission import submit_once


def acquire_claimed(db, notification_id, infohash, magnet_uri, qb):
    """Return a verified torrent hash or None when submission is uncertain.

    Caller owns a claimed episode_dispatch row. Do not mark the episode DONE:
    download and media verification must happen separately.
    """
    if db.in_transaction:
        raise ValueError("Autocommit connection required")
    approved_dispatch(db, notification_id)
    row=db.execute("SELECT info_hash FROM notifications WHERE id=?",
                   (notification_id,)).fetchone()
    if row is None or not row[0]:
        raise ValueError("Notification lacks torrent identity")
    expected=str(row[0]).lower()
    if expected!=infohash.lower():
        raise ValueError("Torrent differs from approved notification")
    return submit_once(db,expected,magnet_uri,qb)
