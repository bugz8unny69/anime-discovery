"""Atomic, idempotent Autobrr intake and explicit episode approval.

Webhook metadata can be approved automatically only when it includes both
external series identities and the exact season/episode. Missing identity
stays in the inbox rather than guessing from the release title.
"""
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, urlsplit

from anime_acquisition_gate import approved_dispatch
from anime_async_daemon import ensure_schema
from anime_release_matching import resolve_release
from anime_batch_selection import release_scope_hint
from anime_trial_policy import eligibility, journal

HASH = re.compile(r"^[0-9a-f]{40}(?:[0-9a-f]{24})?$")


def _positive(value, label):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise ValueError(label + " must be a positive integer") from None
    if result <= 0:
        raise ValueError(label + " must be a positive integer")
    return result


def _magnet(value, infohash):
    magnet = str(value or "magnet:?xt=urn:btih:" + infohash)
    parts = urlsplit(magnet)
    identifiers = parse_qs(parts.query).get("xt", [])
    if parts.scheme != "magnet" or len(identifiers) != 1 or identifiers[0].lower() != "urn:btih:" + infohash:
        raise ValueError("Magnet hash does not match notification")
    return magnet


def _approval_values(values):
    tvdb = str(_positive(values.get("tvdb_id"), "tvdb_id"))
    anidb = str(_positive(values.get("anidb_id"), "anidb_id"))
    season = _positive(values.get("season"), "season")
    episode = _positive(values.get("episode"), "episode")
    return tvdb, anidb, season, episode


def approve(db, notification_id, values, *, source="manual"):
    """Create exactly one approved dispatch and acquisition job in one transaction."""
    nid = _positive(notification_id, "notification_id")
    tvdb, anidb, season, episode = _approval_values(values)
    policy = eligibility(db,tvdb_id=tvdb,anidb_id=anidb,
                         season=season,episode=episode)
    if not policy["eligible"]:
        raise ValueError("Episode outside verified trial window; acquisition refused")
    if db.in_transaction:
        raise ValueError("Approval needs autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        notification = db.execute(
            "SELECT release_name,info_hash FROM notifications WHERE id=?", (nid,)).fetchone()
        if notification is None:
            raise ValueError("Notification not found")
        title, infohash = notification
        infohash = infohash.lower()
        magnet = _magnet(values.get("magnet_uri") or values.get("magnet"), infohash)
        existing = db.execute(
            "SELECT id,status FROM series WHERE source='tvdb' AND external_id=?", (tvdb,)).fetchone()
        if existing:
            sid, status = existing
            if status == "REJECTED" or db.execute(
                "SELECT 1 FROM series_rejection_blocks WHERE series_id=?", (sid,)).fetchone():
                raise ValueError("Series rejected; reset before a new acquisition")
            if db.execute("SELECT 1 FROM series_quarantine WHERE series_id=?", (sid,)).fetchone():
                raise ValueError("Series quarantined")
        prior = db.execute("""SELECT d.series_id,d.season,d.episode,v.tvdb_id,v.anidb_id
             FROM episode_dispatch d JOIN verified_series_identity v
             ON v.notification_id=d.notification_id
             WHERE d.notification_id=?""", (nid,)).fetchone()
        if prior:
            if (str(prior[3]),str(prior[4]),prior[1],prior[2]) != (tvdb,anidb,season,episode):
                raise ValueError("Existing approval conflicts with supplied episode identity")
            job = db.execute("""SELECT payload_json FROM daemon_jobs
                WHERE kind='claimed_acquisition' AND subject_key=?""", (str(nid),)).fetchone()
            if job:
                old = json.loads(job[0])
                if old["magnet_uri"] != magnet:
                    raise ValueError("Existing job uses a different magnet")
                db.commit()
                return {"notification_id": nid, "queued": False, "duplicate": True, "series_id": prior[0]}
            # Repair approval persisted by earlier versions before job enqueue.
            approved_dispatch(db, nid)
            sid = prior[0]
        else:
            if not existing:
                sid = db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb',?,?)",
                                 (tvdb,title)).lastrowid
            else:
                sid = existing[0]
            evidence = json.dumps({"source": source, "tvdb_id": tvdb,
                "anidb_id": anidb, "season": season, "episode": episode}, sort_keys=True)
            db.execute("""INSERT INTO verified_series_identity
                (notification_id,anidb_id,tvdb_id,mapping_source,decision,
                 episode_identity_verified,eligible_for_acquisition,evidence_json,evidence_sha256)
                VALUES (?,?,?,?,'VERIFIED',1,1,?,?)""",
                (nid,anidb,tvdb,source,evidence,hashlib.sha256(evidence.encode()).hexdigest()))
            db.execute("""INSERT INTO episode_verification_v16
                (notification_id,evaluated_at,decision,verified,evidence_json)
                VALUES (?,?,'VERIFIED',1,?)""", (nid,time.time(),evidence))
            db.execute("""INSERT INTO episode_approval_queue
                (notification_id,decision,season,episode)
                VALUES (?,'AUTO_APPROVED',?,?)""", (nid,season,episode))
            db.execute("""INSERT INTO episode_dispatch
                (notification_id,series_id,season,episode,state)
                VALUES (?,?,?,?,'CLAIMED')""", (nid,sid,season,episode))
            db.execute("""INSERT OR IGNORE INTO episodes(series_id,season,episode,status)
                VALUES (?,?,?,'ACQUIRING')""", (sid,season,episode))
        approved_dispatch(db, nid)
        ensure_schema(db)
        payload = json.dumps({"notification_id": nid, "infohash": infohash,
            "magnet_uri": magnet, "title": title, "tvdb_id": tvdb}, sort_keys=True)
        db.execute("""INSERT INTO daemon_jobs(kind,subject_key,payload_json,state)
            VALUES ('claimed_acquisition',?,?,'READY')""", (str(nid),payload))
        db.commit()
        return {"notification_id": nid, "queued": True, "duplicate": False, "series_id": sid}
    except BaseException:
        db.rollback()
        raise


def receive(db, values, *, series_map=None, gap_search_enabled=False):
    """Accept Autobrr metadata. Repeat GUID+hash is idempotent."""
    if not isinstance(values,dict):
        raise ValueError("Expected webhook object")
    source = str(values.get("source") or "autobrr").strip()[:100]
    name = str(values.get("release_name") or values.get("torrentName") or values.get("name") or "").strip()
    infohash = str(values.get("info_hash") or values.get("torrentHash") or values.get("hash") or "").strip().lower()
    guid = str(values.get("source_guid") or values.get("guid") or infohash).strip()[:500]
    if not source or not name or not HASH.fullmatch(infohash) or not guid:
        raise ValueError("Release name and 40/64 character torrent hash required")
    gap_title = None
    if series_map:
        matching_aliases=[alias for alias,entry in series_map.items()
            if str(entry["tvdb_id"])==str(values.get("tvdb_id",""))
            and str(entry["anidb_id"])==str(values.get("anidb_id",""))]
        if len(matching_aliases)==1:
            gap_title=matching_aliases[0]
    if series_map and not any(key in values for key in ("tvdb_id","anidb_id","season","episode")):
        mapped = resolve_release(name,series_map)
        if mapped:
            # One-click Remembered Names are trusted *series* hints, NOT
            # episode approvals. Leave the Autobrr notification in the
            # identity worker until it validates this release's exact episode.
            # Legacy manually entered mappings keep their existing semantics.
            if not mapped.get("requires_episode_verification"):
                values = {**values,**mapped}
            matching_aliases=[alias for alias,entry in series_map.items()
                if str(entry["tvdb_id"])==str(mapped["tvdb_id"])
                and str(entry["anidb_id"])==str(mapped["anidb_id"])]
            if len(matching_aliases)==1:
                gap_title=matching_aliases[0]
    auto_fields = ("tvdb_id","anidb_id","season","episode")
    auto = all(values.get(field) is not None and str(values[field]).strip() for field in auto_fields)
    policy = None
    if auto:
        tvdb, anidb, season, episode = _approval_values(values)
        _magnet(values.get("magnet_uri") or values.get("magnet"), infohash)
        policy = eligibility(db,tvdb_id=tvdb,anidb_id=anidb,
                             season=season,episode=episode)
    if db.in_transaction:
        raise ValueError("Webhook requires autocommit connection")
    db.execute("BEGIN IMMEDIATE")
    try:
        old = db.execute("""SELECT id,info_hash FROM notifications
            WHERE source=? AND source_guid=?""", (source,guid)).fetchone()
        if old and old[1].lower()!=infohash:
            raise ValueError("GUID already belongs to a different torrent")
        if old:
            nid = old[0]
            # A duplicate is idempotent: don't restart identification or
            # present the old terminal review as a new worker run.
        else:
            nid = db.execute("""INSERT INTO notifications
                (source,release_name,source_guid,info_hash,received_at)
                VALUES (?,?,?,?,?)""", (source,name,guid,infohash,int(time.time()))).lastrowid
        if auto and not policy["eligible"]:
            prior=db.execute("SELECT season,episode FROM episode_dispatch WHERE notification_id=?",
                             (nid,)).fetchone()
            if prior and prior!=(season,episode):
                raise ValueError("Existing approval conflicts with supplied episode identity")
            if not prior:
                db.execute("""UPDATE notifications SET status='EXCLUDED_TRIAL_WINDOW'
                    WHERE id=? AND status IN ('UNTRUSTED','RECEIVED','IDENTIFYING')""",
                    (nid,))
        if not auto:
            # Existing alias/identity matching failed to establish an exact
            # episode, so fail closed and require review.
            db.execute("UPDATE notifications SET status='IDENTIFYING' WHERE id=? AND status IN ('UNTRUSTED','RECEIVED') AND NOT EXISTS (SELECT 1 FROM episode_dispatch WHERE notification_id=?)",(nid,nid))
            # The authenticated Autobrr transport is established by /webhook,
            # not by the indexer/feed label in the payload. Persist the magnet;
            # the identity monitor, not this untrusted webhook, decides
            # whether an actual batch acquisition is allowed.
            hint=release_scope_hint(name)
            if hint["kind"]=="season_pack":
                from anime_batch_verified_intake import ensure_schema as batch_schema
                batch_schema(db)
                magnet=_magnet(values.get("magnet_uri") or values.get("magnet"),infohash)
                old_magnet=db.execute("SELECT magnet_uri FROM anime_batch_pending WHERE notification_id=?",(nid,)).fetchone()
                if old_magnet and old_magnet[0]!=magnet:
                    raise ValueError("Duplicate season-pack notification changed magnet identity")
                db.execute("INSERT OR IGNORE INTO anime_batch_pending VALUES (?,?)",(nid,magnet))
        # Upgrade legacy canceled jobs that still occupy the unique subject
        # slot. Only an auditable admin cancellation can be archived.
        if old:
            from anime_job_management import ensure_schema as admin_schema
            admin_schema(db)
            for kind in ("verified_batch_acquisition","claimed_acquisition"):
                archived=db.execute("""SELECT j.id FROM daemon_jobs j
                    JOIN daemon_job_admin_events e ON e.job_id=j.id
                    WHERE j.kind=? AND j.subject_key=? AND j.state='BLOCKED'
                      AND e.id=(SELECT MAX(id) FROM daemon_job_admin_events
                                WHERE job_id=j.id) AND e.action='cancel'""",
                    (kind,str(nid))).fetchone()
                if archived:
                    jid=archived[0]
                    db.execute("""INSERT OR IGNORE INTO daemon_job_archived_subjects
                        (job_id,kind,original_subject_key) VALUES (?,?,?)""",
                        (jid,kind,str(nid)))
                    db.execute("""UPDATE daemon_jobs SET subject_key=?
                        WHERE id=? AND state='BLOCKED' AND subject_key=?""",
                        ("archived:"+str(jid)+":"+str(nid),jid,str(nid)))
        # An explicitly canceled attempt is terminal. On a fresh webhook,
        # reuse persisted verified batch authorization and create a NEW job.
        # The old job remains in archived history and is never reactivated.
        if old:
            from anime_batch_verified_intake import JOB_KIND as BATCH_KIND
            is_verified=db.execute("""SELECT 1 FROM anime_batch_authorizations a
                JOIN notifications n ON n.id=a.notification_id
                WHERE a.notification_id=? AND n.status='APPROVED_BATCH'""",
                (nid,)).fetchone() if db.execute(
                "SELECT 1 FROM sqlite_master WHERE name='anime_batch_authorizations'"
                ).fetchone() else None
            if is_verified:
                from anime_async_daemon import ensure_schema as job_schema
                job_schema(db)
                current=db.execute("""SELECT state FROM daemon_jobs
                    WHERE kind=? AND subject_key=?""",(BATCH_KIND,str(nid))).fetchone()
                if current is None:
                    db.execute("""INSERT INTO daemon_jobs
                        (kind,subject_key,payload_json,state)
                        VALUES (?,?,?,'READY')""",
                        (BATCH_KIND,str(nid),json.dumps({"notification_id":nid})))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    actual_status=db.execute("SELECT status FROM notifications WHERE id=?",(nid,)).fetchone()[0]
    result = {"received": True, "notification_id": nid, "duplicate": bool(old),
              "identity_status": actual_status,
              "identification_pending": actual_status == "IDENTIFYING",
              # Backwards compatible flag, but only true for actual final review.
              "needs_review": actual_status == "NEEDS_REVIEW"}
    if auto:
        if not policy["eligible"]:
            result.update({"queued":False,"excluded":True,
                           "eligibility_reason":policy["reason"]})
            journal("TRIGGER_SKIPPED",reason=policy["reason"],tvdb_id=tvdb,
                    season=season,episode=episode,start=policy["window"]["start"],
                    end=policy["window"]["end"],infohash=infohash)
            if gap_search_enabled and not result["duplicate"] and source=="autobrr":
                from anime_shared_discovery import schedule
                result["gap_search"]=schedule(db,title=gap_title or name,
                    tvdb_id=tvdb,anidb_id=anidb,season=season,
                    up_to=episode,origin="autobrr")["queued"]
            return result
        approved=approve(db,nid,values,source="autobrr")
        result.update(approved)
        if gap_search_enabled and not result["duplicate"] and source=="autobrr":
            from anime_shared_discovery import schedule
            # New episode triggers a bounded catch-up search for earlier episodes.
            # The worker only runs this when Prowlarr has been configured.
            result["gap_search"]=schedule(db,title=gap_title or name,tvdb_id=values["tvdb_id"],
                anidb_id=values["anidb_id"],season=int(values["season"]),
                up_to=int(values["episode"]),origin="autobrr")["queued"]
    return result
