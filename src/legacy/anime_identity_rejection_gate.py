"""Fail-closed canonical identity resolution for incoming notifications.

No release-name fuzzy matching: a verified TVDB identity must already be
bound to exactly one controller series. Call before acquisition or staging.
"""
import sqlite3

class IdentityNotReady(ValueError):
    pass

class SeriesBlocked(ValueError):
    pass

def resolve_notification(db: sqlite3.Connection, notification_id: int) -> int:
    """Return eligible internal series ID; raise on uncertainty or rejection.

    The caller must have initialized the unified schema and stored verified
    identity evidence. This function never creates series or approves episodes.
    """
    if type(notification_id) is not int or notification_id <= 0:
        raise IdentityNotReady("Invalid notification ID")
    notification = db.execute(
        "SELECT status FROM notifications WHERE id=?", (notification_id,)
    ).fetchone()
    if notification is None:
        raise IdentityNotReady("Notification not found")
    if notification[0] not in ("UNTRUSTED", "queued_untrusted"):
        raise IdentityNotReady("Notification not eligible for identity resolution")
    evidence = db.execute(
        "SELECT tvdb_id,episode_identity_verified,eligible_for_acquisition "
        "FROM verified_series_identity WHERE notification_id=?", (notification_id,)
    ).fetchone()
    if evidence is None:
        raise IdentityNotReady("Verified series evidence missing")
    tvdb_id, episode_verified, eligible = evidence
    if not str(tvdb_id).isdigit() or int(tvdb_id) <= 0:
        raise IdentityNotReady("Invalid verified TVDB ID")
    # V8 evidence explicitly prohibits episode approval and acquisition.
    # Resolve series for rejection checks, but do not treat this as permission
    # to download even if an external caller asks for it.
    matches = db.execute(
        "SELECT id,status FROM series WHERE lower(source)='tvdb' AND external_id=?",
        (str(int(tvdb_id)),)
    ).fetchall()
    if len(matches) != 1:
        raise IdentityNotReady("No unique canonical TVDB series binding")
    series_id, status = matches[0]
    # Canonical quarantine on fresh installs; retain legacy rejection checks.
    has_quarantine = db.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='series_quarantine'"
    ).fetchone()
    if has_quarantine and db.execute(
        "SELECT 1 FROM series_quarantine WHERE series_id=?", (series_id,)
    ).fetchone():
        raise SeriesBlocked("Series is quarantined")
    if db.execute(
        "SELECT 1 FROM migration_quarantined_series WHERE series_id=?",
        (series_id,)
    ).fetchone():
        raise SeriesBlocked("Series is quarantined")
    if db.execute(
        "SELECT 1 FROM series_rejection_blocks WHERE series_id=?",
        (series_id,)
    ).fetchone() or status == "REJECTED":
        raise SeriesBlocked("Series rejected")
    if status not in ("DISCOVERED", "ACQUIRING", "PENDING_REVIEW", "NEEDS_REVIEW", "APPROVED"):
        raise IdentityNotReady("Unexpected series state")
    return series_id


def acquisition_authorized(db: sqlite3.Connection, notification_id: int) -> bool:
    """Current V8 evidence is never acquisition authorization."""
    resolve_notification(db, notification_id)
    return False
