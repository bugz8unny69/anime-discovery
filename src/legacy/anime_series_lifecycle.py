"""Series lifecycle controls and dashboard read model.

Clear History hides earlier notifications without breaking acquisition records
or lifting a rejection. Reset is the only action that lifts rejection.
"""


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS series_history_visibility (
        series_id INTEGER PRIMARY KEY REFERENCES series(id),
        clear_before_notification_id INTEGER NOT NULL DEFAULT 0
    )""")


def action(db, series_id, operation):
    result=bulk_action(db,[series_id],operation)
    return {"series_id":series_id,"action":operation,"ok":True}


def bulk_action(db, series_ids, operation):
    """Apply one operation to selected rows in a single database transaction."""
    if operation not in ("reject","clear-history","reset"):
        raise ValueError("Invalid series action")
    if not isinstance(series_ids,(list,tuple)) or not 1<=len(series_ids)<=100:
        raise ValueError("Select between one and 100 series")
    ids=[]
    for raw in series_ids:
        if type(raw) not in (int,str) or not str(raw).isdigit() or int(raw)<=0:
            raise ValueError("Invalid series ID")
        ids.append(int(raw))
    if len(set(ids))!=len(ids):
        raise ValueError("Duplicate series ID")
    if db.in_transaction:
        raise ValueError("Series actions need autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        ensure_schema(db)
        for sid in ids:
            row=db.execute("SELECT status FROM series WHERE id=?",(sid,)).fetchone()
            if row is None:
                raise ValueError("Series not found: "+str(sid))
            if operation=="reject":
                db.execute("UPDATE series SET status='REJECTED' WHERE id=?",(sid,))
                db.execute("""INSERT OR REPLACE INTO series_rejection_blocks
                    (series_id,reason) VALUES (?,'USER_REJECTED')""",(sid,))
                db.execute("""UPDATE daemon_jobs SET state='BLOCKED',last_error='Series rejected'
                    WHERE kind='claimed_acquisition' AND state IN ('READY','DEFERRED')
                    AND subject_key IN (SELECT CAST(d.notification_id AS TEXT)
                        FROM episode_dispatch d WHERE d.series_id=?)""",(sid,))
            elif operation=="clear-history":
                cutoff=db.execute("""SELECT COALESCE(MAX(v.notification_id),0)
                    FROM verified_series_identity v WHERE v.tvdb_id=(
                    SELECT external_id FROM series WHERE id=? AND source='tvdb')""",(sid,)).fetchone()[0]
                db.execute("""INSERT INTO series_history_visibility
                    (series_id,clear_before_notification_id) VALUES (?,?)
                    ON CONFLICT(series_id) DO UPDATE SET
                    clear_before_notification_id=MAX(clear_before_notification_id,excluded.clear_before_notification_id)""",
                    (sid,cutoff))
            else:
                db.execute("DELETE FROM series_rejection_blocks WHERE series_id=?",(sid,))
                db.execute("DELETE FROM series_quarantine WHERE series_id=?",(sid,))
                db.execute("""UPDATE series SET status='DISCOVERED',
                    initial_search_complete=0 WHERE id=?""",(sid,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"series_ids":ids,"action":operation,"updated":len(ids),"ok":True}


def notifications(db, limit=100):
    ensure_schema(db)
    return db.execute("""SELECT n.id,n.source,n.release_name,n.info_hash,n.status,
        COALESCE(d.state,'INBOX') AS dispatch_state,
        COALESCE(j.state,'') AS job_state
        FROM notifications n
        LEFT JOIN verified_series_identity v ON v.notification_id=n.id
        LEFT JOIN series s ON s.source='tvdb' AND s.external_id=v.tvdb_id
        LEFT JOIN series_history_visibility h ON h.series_id=s.id
        LEFT JOIN episode_dispatch d ON d.notification_id=n.id
        LEFT JOIN daemon_jobs j ON j.kind='claimed_acquisition'
            AND j.subject_key=CAST(n.id AS TEXT)
        WHERE h.clear_before_notification_id IS NULL
           OR n.id>h.clear_before_notification_id
        ORDER BY n.id DESC LIMIT ?""", (limit,)).fetchall()


def inspect(db, series_id):
    series_id=int(series_id)
    if series_id<=0:
        raise ValueError("Invalid series ID")
    ensure_schema(db)
    row=db.execute("""SELECT id,title,external_id,status,initial_search_complete
        FROM series WHERE id=?""", (series_id,)).fetchone()
    if row is None:
        raise ValueError("Series not found")
    episodes=db.execute("""SELECT season,episode,status FROM episodes
        WHERE series_id=? ORDER BY season,episode""", (series_id,)).fetchall()
    releases=db.execute("""SELECT n.id,n.release_name,d.season,d.episode,d.state,
        COALESCE(j.state,'NO_JOB'),COALESCE(r.staged_path,'')
        FROM episode_dispatch d
        JOIN notifications n ON n.id=d.notification_id
        LEFT JOIN daemon_jobs j ON j.kind='claimed_acquisition'
           AND j.subject_key=CAST(d.notification_id AS TEXT)
        LEFT JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
        WHERE d.series_id=? ORDER BY n.id DESC""",(series_id,)).fetchall()
    rejected=bool(db.execute(
        "SELECT 1 FROM series_rejection_blocks WHERE series_id=?", (series_id,)).fetchone())
    return {"series":row, "episodes":episodes, "releases":releases, "rejected":rejected}
