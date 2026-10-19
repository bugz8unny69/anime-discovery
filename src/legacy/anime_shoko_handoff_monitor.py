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
from anime_ntfy import notify_shoko_issue
from anime_episode_identity import resolve_exact_episode
from anime_episode_crossref import tvdb_episode_id, resolve_anidb_episode
from anime_shoko_handoff_state import record_verified_episode
from anime_shoko_write import request_scan, link_verified

LOG=logging.getLogger(__name__)

def check_once(settings,secrets,*,inspector=None,copy_verifier=None,alert_sender=notify_shoko_issue):
    if not settings["sonarr"]["enabled"] or not settings["shoko"]["enabled"]:
        return {"processed":0,"disabled":True}
    copy_verifier=copy_verifier or confirm_sonarr_copies
    with sqlite3.connect(settings["daemon"]["database_path"],isolation_level=None,
                         timeout=10) as db:
        db.execute("PRAGMA busy_timeout=10000")
        ensure_schema(db)
        db.execute("""CREATE TABLE IF NOT EXISTS shoko_alert_delivery (
            series_id INTEGER NOT NULL, notification_id INTEGER NOT NULL,
            reason TEXT NOT NULL, PRIMARY KEY(series_id,notification_id,reason)
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS shoko_scan_attempts (
            series_id INTEGER NOT NULL, notification_id INTEGER NOT NULL,
            last_attempt INTEGER NOT NULL, PRIMARY KEY(series_id,notification_id)
        )""")
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
                    current=db.execute("""SELECT identity_verified FROM shoko_handoff
                        WHERE series_id=? AND notification_id=?""",
                        (series_id,nid)).fetchone()
                    if current and current[0]!=1 and (
                            settings.get("identity",{}).get("episode_map")
                            or settings.get("tvdb",{}).get("enabled")):
                        tvdb=db.execute("SELECT external_id FROM series WHERE id=? AND source='tvdb'",
                                        (series_id,)).fetchone()
                        if tvdb and str(tvdb[0]).isdigit():
                            tvdb_id=int(tvdb[0])
                            episode_id=resolve_exact_episode(settings,tvdb_id=tvdb_id,
                                season=entry["season"],episode=entry["episode"])
                            if not episode_id and settings.get("tvdb",{}).get("enabled"):
                                verified=db.execute("""SELECT anidb_id,tvdb_id
                                    FROM verified_series_identity WHERE notification_id=?""",
                                    (nid,)).fetchone()
                                if verified and str(verified[1])==str(tvdb_id) and str(verified[0]).isdigit():
                                    tvdb_ep=tvdb_episode_id(settings,secrets,tvdb_id=tvdb_id,
                                        season=entry["season"],episode=entry["episode"])
                                    if tvdb_ep:
                                        episode_id=resolve_anidb_episode(
                                            settings["shoko"]["base_url"],
                                            secrets["shoko_api_key"],
                                            anidb_series_id=int(verified[0]),
                                            tvdb_episode_id=tvdb_ep)
                            if episode_id:
                                record_verified_episode(db,series_id=series_id,
                                    notification_id=nid,anidb_episode_id=episode_id)
                    if status in ("SHOKO_ALREADY_LINKED_VERIFIED","SHOKO_LINK_VERIFIED"):
                        continue
                    observation=reconcile_one(db,settings,secrets,series_id=series_id,
                                  notification_id=nid,inspector=inspector)
                    reason=observation["status"]
                    if reason=="AWAITING_SHOKO_SCAN":
                        # A scan is optional and rate-limited: only the configured
                        # permanent Anime import folder, never torrent staging.
                        folder=settings["shoko"].get("import_folder_id",0)
                        if folder>0:
                            last=db.execute("""SELECT last_attempt FROM shoko_scan_attempts
                                WHERE series_id=? AND notification_id=?""",
                                (series_id,nid)).fetchone()
                            now=int(time.time())
                            if last is None or now-last[0]>=3600:
                                try:
                                    request_scan(settings["shoko"]["base_url"],
                                                 secrets["shoko_api_key"],folder,
                                                 expected_root=settings["sonarr"]["root_folder"])
                                    db.execute("""INSERT INTO shoko_scan_attempts VALUES (?,?,?)
                                        ON CONFLICT(series_id,notification_id)
                                        DO UPDATE SET last_attempt=excluded.last_attempt""",
                                        (series_id,nid,now))
                                except Exception:
                                    LOG.warning("Shoko scan request failed for series %d",series_id)
                    if reason=="LINK_PLAN_READY" and settings["shoko"].get("auto_link_verified") is True:
                        try:
                            verified=link_verified(settings["shoko"]["base_url"],
                                secrets["shoko_api_key"],
                                file_id=observation["file_id"],
                                shoko_episode_id=observation["shoko_episode_id"],
                                anidb_episode_id=observation["anidb_episode_id"],
                                verified_identity=True,allow_writes=True)
                            db.execute("""UPDATE shoko_handoff SET status=?
                                WHERE series_id=? AND notification_id=?""",
                                (verified,series_id,nid))
                            reason=verified
                        except Exception:
                            reason="SHOKO_LINK_FAILED"
                            LOG.warning("Shoko episode link failed for series %d",series_id)
                    elif reason=="LINK_PLAN_READY":
                        reason="SHOKO_LINK_DISABLED"
                    # Only send one alert per issue state; a failed send is retried
                    # on a later poll. Shoko is never permitted to block Keep.
                    if settings.get("ntfy",{}).get("enabled") and reason in (
                            "NEEDS_EPISODE_IDENTITY","UNRECOGNIZED_NEEDS_REVIEW",
                            "AMBIGUOUS_SHOKO_FILE","AMBIGUOUS_SHOKO_LINK",
                            "CONFLICTING_SHOKO_LINK","SHOKO_LINK_FAILED","SHOKO_LINK_DISABLED"):
                        sent=db.execute("""SELECT 1 FROM shoko_alert_delivery
                            WHERE series_id=? AND notification_id=? AND reason=?""",
                            (series_id,nid,reason)).fetchone()
                        if not sent:
                            try:
                                if alert_sender(settings,secrets,series_id,nid,reason):
                                    db.execute("""INSERT OR IGNORE INTO shoko_alert_delivery
                                        VALUES (?,?,?)""",(series_id,nid,reason))
                            except Exception:
                                LOG.warning("Shoko alert deferred for series %d",series_id)
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
