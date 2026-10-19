"""Read-only Shoko handoff monitor for Anime Discovery Kept imports.

Does not mutate Sonarr, Shoko, qBittorrent or media. Restarts are safe:
backfill provenance only after re-verifying Sonarr copies against recovery hashes.
"""
import json
import logging
import sqlite3
import time
from anime_flat_config import load_config
from anime_sonarr_finalize import confirm_sonarr_copies
from anime_shoko_handoff_state import ensure_schema, enqueue_verified_copies, reconcile_one

LOG=logging.getLogger(__name__)

def check_once(settings,secrets,*,inspector=None,copy_verifier=None):
    if not settings["sonarr"]["enabled"] or not settings["shoko"]["enabled"]:
        return {"processed":0,"disabled":True}
    copy_verifier=copy_verifier or confirm_sonarr_copies
    with sqlite3.connect(settings["daemon"]["database_path"],isolation_level=None,
                         timeout=10) as db:
        db.execute("PRAGMA busy_timeout=10000")
        ensure_schema(db)
        series=db.execute("""SELECT s.id,k.sonarr_id,m.manifest_json
            FROM series s JOIN sonarr_keep k ON k.series_id=s.id
            JOIN sonarr_import_manifest m ON m.series_id=s.id
            WHERE s.status='KEPT' ORDER BY s.id LIMIT 20""").fetchall()
        processed=0
        errors=0
        for series_id,sonarr_id,raw in series:
            try:
                manifest=json.loads(raw)
                if not isinstance(manifest,list) or not manifest:
                    raise ValueError("Invalid Keep manifest")
                ids=[entry["notification_id"] for entry in manifest]
                if len(set(ids))!=len(ids) or any(type(i) is not int for i in ids):
                    raise ValueError("Invalid Keep provenance")
                records=db.execute("""SELECT notification_id,sha256
                    FROM torrent_recovery_records WHERE notification_id IN ("""+
                    ",".join("?" for _ in ids)+")",ids).fetchall()
                digests={i:d.lower() for i,d in records
                         if isinstance(d,str) and len(d)==64
                         and all(c in "0123456789abcdef" for c in d.lower())}
                if len(digests)!=len(ids):
                    raise ValueError("Missing trusted import digests")
                destinations=copy_verifier(settings,secrets,sonarr_id=sonarr_id,
                    plan=manifest,expected_digests=digests)
                # Queue only paths returned by verified Sonarr episode inventory.
                enqueue_verified_copies(db,series_id,manifest,destinations)
                for entry in manifest:
                    nid=entry["notification_id"]
                    status=db.execute("""SELECT status FROM shoko_handoff
                        WHERE series_id=? AND notification_id=?""",
                        (series_id,nid)).fetchone()[0]
                    if status in ("SHOKO_ALREADY_LINKED","LINK_PLAN_READY"):
                        continue
                    reconcile_one(db,settings,secrets,series_id=series_id,
                                  notification_id=nid,inspector=inspector)
                    processed+=1
            except Exception as exc:
                errors+=1
                LOG.warning("Shoko handoff deferred for series %d (%s)",
                            series_id,type(exc).__name__)
        return {"processed":processed,"errors":errors}

def main():
    while True:
        try:
            cfg=load_config()
            check_once(cfg["settings"],cfg["secrets"])
        except Exception as exc:
            LOG.warning("Shoko monitor deferred (%s)",type(exc).__name__)
        time.sleep(60)

if __name__=="__main__":
    main()
