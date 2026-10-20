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


def ensure_cleanup_notice_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS sonarr_keep_cleanup_notice (
        series_id INTEGER NOT NULL REFERENCES series(id),
        infohash TEXT NOT NULL,
        ownership TEXT NOT NULL CHECK(ownership IN ('EXTERNAL','UNCERTAIN')),
        created_at INTEGER NOT NULL,
        PRIMARY KEY(series_id,infohash))""")


def keep(db, series_id, settings, secrets, *, sonarr_client=None, import_client=None):
    """Admit series to Sonarr, then track pending episode import. No deletion."""
    from anime_sonarr import ensure_series
    from anime_qb_ownership import OWNED, ownership_for_series
    if type(series_id) is not int or series_id<=0 or db.in_transaction:
        raise ValueError("Invalid Keep request")
    row=db.execute("SELECT external_id,title,status FROM series WHERE id=? AND source='tvdb'",(series_id,)).fetchone()
    if row is None or not str(row[0]).isdigit() or int(row[0])<=0:
        raise ValueError("Series lacks TVDB identity")
    if row[2] in ("SONARR_IMPORT_PENDING","KEPT"):
        raise ValueError("Keep already submitted or completed")
    if row[2]=="REJECTED" or db.execute("SELECT 1 FROM series_rejection_blocks WHERE series_id=?",(series_id,)).fetchone():
        raise ValueError("Rejected series requires reset")
    from pathlib import Path
    paths=db.execute("""SELECT r.staged_path FROM episode_dispatch d
        JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
        WHERE d.series_id=? AND d.state='DONE'""",(series_id,)).fetchall()
    if not any(path and Path(path).is_file() for (path,) in paths):
        raise ValueError("Keep requires an existing staged episode")
    # Don't import E01 while E02–E06 from its same batch are still pending:
    # that would freeze Sonarr's import manifest before its source matches
    # the downloaded file selection, preventing safe final cleanup.
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anime_batch_executions'").fetchone():
        unfinished=db.execute("""SELECT x.state FROM anime_batch_executions x
            JOIN anime_batch_authorizations a ON a.notification_id=x.notification_id
            WHERE a.tvdb_id=? AND x.state!='DONE' LIMIT 1""",(str(row[0]),)).fetchone()
        if unfinished:
            raise ValueError("Batch trial not yet fully staged; finish or review its acquisition job")
    if settings.get("tvdb",{}).get("enabled") is True:
        from anime_tvdb import lookup_tvdb
        resolved=lookup_tvdb(settings,secrets,row[0])
        if resolved["tvdb_id"]!=int(row[0]):
            raise RuntimeError("TVDB identity verification failed")
    result=(sonarr_client or ensure_series)(settings,secrets,tvdb_id=row[0],title=row[1])
    if not isinstance(result,dict) or type(result.get("sonarr_id")) is not int or result["sonarr_id"]<=0:
        raise RuntimeError("Sonarr admission unconfirmed")
    from anime_sonarr_import import plan_staged_imports
    # Capture import manifest; a separate explicit action submits to Sonarr.
    trial_root=settings.get("storage",{}).get("trial_root")
    if not trial_root:
        raise ValueError("Trial root must be configured")
    manifest=plan_staged_imports(db,series_id,trial_root=trial_root)
    # Preserve ownership decisions at Keep time for a durable, human-readable
    # notice on the series page. Never infer ownership from qB category alone.
    preserved=[row for row in ownership_for_series(db,series_id)
               if row["ownership"]!=OWNED]
    command_id=None
    if sonarr_client is None or import_client is not None:
        from anime_sonarr_import import request_import
        submitted=(import_client or request_import)(settings,secrets,
            sonarr_id=result["sonarr_id"],plan=manifest)
        command_id=submitted.get("command_id")
        if type(command_id) is not int or command_id<=0:
            raise RuntimeError("Sonarr did not confirm import submission")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""CREATE TABLE IF NOT EXISTS sonarr_keep (
            series_id INTEGER PRIMARY KEY REFERENCES series(id),
            sonarr_id INTEGER NOT NULL, tvdb_id TEXT NOT NULL,
            kept_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")
        db.execute("""INSERT INTO sonarr_keep(series_id,sonarr_id,tvdb_id)
            VALUES (?,?,?) ON CONFLICT(series_id) DO UPDATE SET sonarr_id=excluded.sonarr_id""",
            (series_id,result["sonarr_id"],str(row[0])))
        db.execute("""CREATE TABLE IF NOT EXISTS sonarr_import_manifest (
            series_id INTEGER PRIMARY KEY REFERENCES series(id),
            manifest_json TEXT NOT NULL,
            submitted_command_id INTEGER
        )""")
        import json
        db.execute("""INSERT INTO sonarr_import_manifest(series_id,manifest_json,submitted_command_id)
            VALUES (?,?,?) ON CONFLICT(series_id) DO UPDATE SET
            manifest_json=excluded.manifest_json,
            submitted_command_id=excluded.submitted_command_id""",
            (series_id,json.dumps(manifest),command_id))
        ensure_cleanup_notice_schema(db)
        db.execute("DELETE FROM sonarr_keep_cleanup_notice WHERE series_id=?",(series_id,))
        from time import time
        db.executemany("""INSERT INTO sonarr_keep_cleanup_notice
            (series_id,infohash,ownership,created_at) VALUES (?,?,?,?)""",
            [(series_id,row["infohash"],row["ownership"],int(time()))
             for row in preserved])
        db.execute("UPDATE series SET status='SONARR_IMPORT_PENDING' WHERE id=?",(series_id,))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    return {"series_id":series_id,"action":"keep","sonarr_id":result["sonarr_id"],"ok":True,
            "trial_media_preserved":True,"import_pending":True,"command_id":command_id,
            "torrent_cleanup_authorized":False,"torrents_preserved":len(preserved),
            "cleanup_notice":"Original qBittorrent torrents will be preserved for manual removal after Sonarr import." if preserved else None}


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
    cleanup_notices=[]
    if row[3] in ("SONARR_IMPORT_PENDING","KEPT"):
        ensure_cleanup_notice_schema(db)
        cleanup_notices=[{"infohash":hash_value,"ownership":ownership_state}
            for hash_value,ownership_state in db.execute(
                """SELECT infohash,ownership FROM sonarr_keep_cleanup_notice
                   WHERE series_id=? ORDER BY infohash""",(series_id,))]
    return {"series":row,"episodes":episodes,"releases":releases,
            "rejected":rejected,"cleanup_notices":cleanup_notices}
