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
