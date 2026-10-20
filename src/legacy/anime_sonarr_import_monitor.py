"""Poll pending Sonarr manual-copy imports and safely finalize completed Keeps."""
import logging
import sqlite3
import time
from anime_config_wakeup import wait_for_change
from anime_flat_config import load_config
from anime_qb_api import QBittorrentAPI
from anime_sonarr_finalize import finalize_import

LOG=logging.getLogger(__name__)

def check_once(settings,secrets,*,qb_factory=None):
    if not settings["sonarr"]["enabled"]:
        return {"processed":0}
    if qb_factory is None:
        def qb_factory():
            cfg=settings["qbittorrent"]
            client=QBittorrentAPI(cfg["base_url"],allow_writes=True)
            client.login(cfg["username"],secrets["qbittorrent_password"])
            return client
    path=settings["daemon"]["database_path"]
    with sqlite3.connect(path,isolation_level=None,timeout=10) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=10000")
        if not db.execute("SELECT 1 FROM sqlite_master WHERE name='sonarr_import_manifest'").fetchone():
            return {"processed":0}
        pending=db.execute("""SELECT s.id FROM series s
            JOIN sonarr_import_manifest m ON m.series_id=s.id
            WHERE s.status='SONARR_IMPORT_PENDING'
              AND m.submitted_command_id IS NOT NULL ORDER BY s.id LIMIT 20""").fetchall()
        # Reuse this existing monitor for bounded, read-only six-hour checks.
        # Never treat an unavailable Sonarr as permission to delete anything.
        from anime_sonarr_reconciliation import ensure_schema, check_series
        ensure_schema(db)
        interval=21600
        stale=int(time.time())-interval
        candidates=db.execute("""SELECT DISTINCT s.id FROM series s
            JOIN episode_dispatch d ON d.series_id=s.id AND d.state='DONE'
            JOIN torrent_recovery_records r ON r.notification_id=d.notification_id
            LEFT JOIN sonarr_reconciliation rc ON rc.series_id=s.id
            WHERE s.source='tvdb' AND s.status NOT IN ('REJECTED')
              AND (rc.checked_at IS NULL OR rc.checked_at<=?)
            ORDER BY COALESCE(rc.checked_at,0),s.id LIMIT 5""",(stale,)).fetchall()
        for (sid,) in candidates:
            try:
                check_series(db,sid,settings,secrets)
            except Exception as exc:
                # Retry at the next cadence, never block normal import finalization.
                LOG.warning("event=SONARR_RECONCILIATION_DEFERRED series_id=%d error_type=%s",
                            sid,type(exc).__name__)
                db.execute("""INSERT INTO sonarr_reconciliation
                    (series_id,checked_at,result,inventory_json,error_reason)
                    VALUES (?,?,'UNAVAILABLE','[]',?)
                    ON CONFLICT(series_id) DO UPDATE SET checked_at=excluded.checked_at,
                    result=excluded.result,error_reason=excluded.error_reason,
                    inventory_json='[]'""",(sid,int(time.time()),type(exc).__name__))
        complete=0
        errors=0
        for (sid,) in pending:
            try:
                result=finalize_import(db,sid,settings,secrets,qb=qb_factory())
                complete+=int(result["complete"])
            except Exception as exc:
                errors+=1
                # Do not log upstream URLs or credential-bearing exception strings.
                LOG.warning("Sonarr Keep finalization deferred for series %d (%s)",sid,type(exc).__name__)
        return {"processed":len(pending),"complete":complete,"errors":errors}

def main():
    while True:
        try:
            config=load_config()
            check_once(config["settings"],config["secrets"])
        except Exception as exc:
            LOG.warning("Sonarr Keep monitor iteration deferred (%s)",type(exc).__name__)
        wait_for_change(60)

if __name__=="__main__":
    main()
