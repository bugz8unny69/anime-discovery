"""Atomic episode acquisition slot: only one release group per TVDB episode.

A slot is acquired only when the worker actually begins acquisition, not at
webhook approval. STAGED means validated Jellyfin trial, not manual Keep.
"""
import sqlite3

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_episode_acquisition_slots (
      tvdb_id TEXT NOT NULL, season INTEGER NOT NULL, episode INTEGER NOT NULL,
      owner_notification_id INTEGER NOT NULL,
      state TEXT NOT NULL CHECK(state IN ('ACTIVE','STAGED')),
      PRIMARY KEY(tvdb_id,season,episode))""")

def reserve(db, notification_id):
    """Return OWNER, ON_HOLD, or SKIPPED_DUPLICATE; serialized in SQLite."""
    if db.in_transaction:
        raise ValueError("Episode slot needs autocommit")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        row=db.execute("""SELECT s.external_id,d.season,d.episode
          FROM episode_dispatch d JOIN series s ON s.id=d.series_id
          WHERE d.notification_id=? AND s.source='tvdb'""",(notification_id,)).fetchone()
        if not row:
            raise ValueError("Verified dispatch missing for episode slot")
        key=(str(row[0]),row[1],row[2])
        slot=db.execute("""SELECT owner_notification_id,state
            FROM anime_episode_acquisition_slots
            WHERE tvdb_id=? AND season=? AND episode=?""",key).fetchone()
        if slot is None:
            db.execute("""INSERT INTO anime_episode_acquisition_slots
                VALUES (?,?,?,?,'ACTIVE')""",(*key,notification_id))
            answer="OWNER"
        elif slot[1]=="STAGED":
            answer="OWNER" if slot[0]==notification_id else "SKIPPED_DUPLICATE"
        else:
            answer="OWNER" if slot[0]==notification_id else "ON_HOLD"
        db.commit()
        return answer
    except BaseException:
        db.rollback()
        raise

def mark_staged(db,notification_id):
    """Mark successful Jellyfin trial staging; never infer manual Keep."""
    if db.in_transaction:
        raise ValueError("Episode slot needs autocommit")
    db.execute("BEGIN IMMEDIATE")
    try:
        changed=db.execute("""UPDATE anime_episode_acquisition_slots
            SET state='STAGED' WHERE owner_notification_id=? AND state='ACTIVE'
            AND EXISTS(SELECT 1 FROM episode_dispatch d
              WHERE d.notification_id=? AND d.state='DONE')""",
              (notification_id,notification_id)).rowcount
        if changed!=1:
            raise ValueError("Stage confirmation requires owned slot and completed dispatch")
        db.execute("""UPDATE daemon_jobs SET available_at=0
          WHERE kind='claimed_acquisition' AND state='DEFERRED'
            AND last_error='ON_HOLD' AND subject_key IN (
            SELECT CAST(d.notification_id AS TEXT) FROM episode_dispatch d
            JOIN series se ON se.id=d.series_id
            JOIN anime_episode_acquisition_slots slot
              ON slot.tvdb_id=se.external_id
             AND slot.season=d.season AND slot.episode=d.episode
            WHERE slot.owner_notification_id=? AND slot.state='STAGED'
          )""",(notification_id,))
        db.commit()
    except BaseException:
        db.rollback()
        raise

def competing_claim(db,tvdb_id,season,episode,notification_id):
    """Legacy informational helper; worker reservations own arbitration."""
    ensure_schema(db)
    row=db.execute("""SELECT owner_notification_id
        FROM anime_episode_acquisition_slots
        WHERE tvdb_id=? AND season=? AND episode=?
          AND owner_notification_id<>?""",
        (str(tvdb_id),season,episode,notification_id)).fetchone()
    return row[0] if row else None

class CompetingEpisodeAcquisition(ValueError):
    def __init__(self,notification_id):
        self.notification_id=int(notification_id)
        super().__init__("Verified episode already claimed")
