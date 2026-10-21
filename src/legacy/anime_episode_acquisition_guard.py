"""Episode-level competing acquisition detection.

Call while holding the approval transaction's BEGIN IMMEDIATE write lock.
A release-group label or torrent hash is not an episode-level dedup key.
"""
class CompetingEpisodeAcquisition(ValueError):
    """A different notification already owns this exact TVDB episode."""
    def __init__(self, notification_id):
        self.notification_id=int(notification_id)
        super().__init__("Verified episode has an existing acquisition claim")

def competing_claim(db, tvdb_id, season, episode, notification_id):
    """Find any previously claimed acquisition for the same TVDB episode.

    Fail closed across READY, LEASED, DEFERRED, DONE or BLOCKED jobs; even
    a failed job may have left files/torrents that require reconciliation.
    An operator can inspect and safely release a claim in a future workflow.
    """
    row=db.execute("""SELECT d.notification_id
        FROM episode_dispatch AS d
        JOIN series AS s ON s.id=d.series_id
        WHERE s.source='tvdb' AND s.external_id=?
          AND d.season=? AND d.episode=? AND d.notification_id<>?
        ORDER BY d.notification_id LIMIT 1""",
        (str(tvdb_id),season,episode,notification_id)).fetchone()
    return int(row[0]) if row else None
