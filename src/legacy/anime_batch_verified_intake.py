"""Authorize an Autobrr season pack only after independent provider identity triage.

Called from the existing identity monitor, NEVER from a webhook-provided pair.
Requires admin-pinned series alias/season, single TVDB/AniDB cross-reference,
independent Anime-Lists pair corroboration, and exact incoming torrent hash.
Episode numbers and file sizes are still verified after qB metadata arrives.
"""
import hashlib
import json
import logging
import re

from anime_batch_selection import release_scope_hint
from anime_identity_mapping_v4 import mappings, resolve_episode
from anime_identification_probe import release_title, norm
from anime_trial_policy import record_verified_window, window_for

LOG = logging.getLogger("anime_discovery.trial")
JOB_KIND = "verified_batch_acquisition"


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anime_batch_pending (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        magnet_uri TEXT NOT NULL
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS anime_batch_authorizations (
        notification_id INTEGER PRIMARY KEY REFERENCES notifications(id),
        tvdb_id TEXT NOT NULL, anidb_id TEXT NOT NULL,
        season INTEGER NOT NULL, unit_key TEXT NOT NULL,
        title TEXT NOT NULL, xml_sha256 TEXT NOT NULL,
        infohash TEXT NOT NULL,
        UNIQUE(tvdb_id,season,unit_key)
    )""")


def verified_pack_candidate(db, notification_id, report, settings, xml_bytes):
    """Authorize only a genuinely pinned, independently cross-checked batch.

    A failed candidate now records the first precise *authorization* blocker
    in identity evidence. The old broad manifest/episode-missing issues are
    expected for packs; they must not hide the actual unfulfilled precondition.
    """
    if not isinstance(report,dict) or not isinstance(settings,dict):
        return None

    def blocked(reason, action):
        report["batch_authorization"]={"decision":"BLOCKED",
                                        "reason":reason,"action":action}
        # Put the actionable blocker first; the Jobs dashboard shows only
        # the first three issues and previously displayed only generic pack
        # indicators while hiding the actual authorization failure.
        report["issues"]=[reason]+[code for code in (report.get("issues") or [])
                                   if code!=reason]
        report.setdefault("workflow",[]).append(
            {"step":"Batch authorization","decision":"BLOCKED",
             "reason":reason,"action":action})
        LOG.warning("event=BATCH_AUTHORIZATION_BLOCKED notification=%s reason=%s",
                    notification_id,reason)
        return None

    if not isinstance(xml_bytes,bytes) or not xml_bytes:
        return blocked("BATCH_ANIME_LISTS_UNAVAILABLE",
                       "Refresh the trusted Anime-Lists cache before verifying a pack")
    row=db.execute("""SELECT n.release_name,n.info_hash,n.source,p.magnet_uri
        FROM notifications n JOIN anime_batch_pending p ON p.notification_id=n.id
        WHERE n.id=?""",(notification_id,)).fetchone()
    if not row:
        return blocked("BATCH_PENDING_MAGNET_MISSING",
                       "Autobrr season packs require an intake record with a trusted magnet")
    title,infohash,source,_magnet=row
    if source!="autobrr":
        return blocked("BATCH_NOT_AUTOBRR",
                       "Batch intake is authorized only for Autobrr notifications")
    hint=release_scope_hint(title)
    if hint["kind"]!="season_pack":
        return blocked("BATCH_RELEASE_SCOPE_UNSUPPORTED",
                       "Release title must explicitly identify a season pack")
    season=hint.get("season_hint")
    if type(season) is not int or season<=0:
        return blocked("BATCH_SEASON_HINT_REQUIRED",
                       "Release name must contain an unambiguous S01 or Season 01; never assume season 1 from a batch label")
    names,_=release_title(title)
    if not names:
        return blocked("BATCH_SERIES_TITLE_UNRESOLVED",
                       "Cannot extract the anime title from the Autobrr release name")
    aliases=settings.get("identity",{}).get("series_map",{})
    if not isinstance(aliases,dict):
        return blocked("BATCH_PINNED_ALIASES_INVALID",
                       "Fix identity.series_map in Recognized names")
    title_matches=[(alias,identity) for alias,identity in aliases.items()
                   if norm(alias)==norm(names[0]) and isinstance(identity,dict)]
    matches=[(alias,identity) for alias,identity in title_matches
             if identity.get("season",1)==season]
    if not matches:
        code=("BATCH_PINNED_SEASON_MISMATCH" if title_matches
              else "BATCH_PINNED_ALIAS_MISSING")
        return blocked(code,
                       "In Recognized names, pin this release title to its verified TVDB and AniDB IDs and the season shown in the release")
    if len(matches)!=1:
        return blocked("BATCH_PINNED_ALIAS_AMBIGUOUS",
                       "Resolve multiple aliases for the same normalized title and season")
    alias,identity=matches[0]
    try:
        tvdb=str(int(identity["tvdb_id"]))
        anidb=str(int(identity["anidb_id"]))
    except (KeyError,ValueError,TypeError):
        return blocked("BATCH_PINNED_IDS_INVALID",
                       "Recognized names must contain valid TVDB and AniDB numeric IDs")
    if tvdb=="0" or anidb=="0":
        return blocked("BATCH_PINNED_IDS_INVALID",
                       "Recognized names must contain positive TVDB and AniDB IDs")
    pairs=report.get("matching_pairs")
    if (not isinstance(pairs,list) or len(pairs)!=1 or
            str(pairs[0].get("tvdb_id"))!=tvdb or
            str(pairs[0].get("anidb_id"))!=anidb):
        return blocked("BATCH_PINNED_PROVIDER_PAIR_MISMATCH",
                       "Recognized names IDs must agree with the unique independently verified TVDB/AniDB pair")
    issues=set(report.get("issues") or [])
    expected={"BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED",
              "EXACT_IDENTITY_NOT_VERIFIED"}
    if not {"BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED"}.issubset(issues) or issues-expected:
        return blocked("BATCH_OTHER_IDENTITY_ISSUES",
                       "Resolve conflicting provider, media type or episode evidence before downloading")
    diagnostic=[r for r in report.get("crossref_diagnostics",[])
                if str(r.get("tvdb_id"))==tvdb]
    if (len(diagnostic)!=1 or diagnostic[0].get("media_type")!="ANIMATION"
            or anidb not in [str(n) for n in diagnostic[0].get("matching_anidb_ids",[])]):
        return blocked("BATCH_ANIMATION_CROSSREF_UNVERIFIED",
                       "Exact animated-media classification and provider ID match are required")
    # Authenticate a unique actual pair from the independent XML source.
    try:
        mapped=mappings(xml_bytes,anidb)
    except Exception:
        return blocked("BATCH_ANIME_LISTS_MAPPING_UNREADABLE",
                       "Anime-Lists mapping cannot be read or validated")
    if len(mapped)!=1 or mapped[0].get("tvdbid")!=tvdb:
        return blocked("BATCH_ANIME_LISTS_PAIR_NOT_UNIQUE",
                       "Exactly one independent Anime-Lists TVDB/AniDB mapping is required")
    unit_key,mode,start="season","SEASON",1
    part=re.search(r"(?i)(?<![a-z0-9])(?:Part|Cour)[ ._-]*([2-9])(?!\d)",title)
    if part:
        # Part 2 of the same provider season can begin at canonical E13,
        # but ONLY when an explicit AniDB episode-1 -> TVDB boundary agrees.
        part_no=int(part.group(1))
        target=resolve_episode(xml_bytes,int(anidb),int(tvdb),1)
        if not target or target["tvdb_season"]!=season or target["tvdb_episode"]<=1:
            return blocked("BATCH_PART_BOUNDARY_UNVERIFIED",
                           "Part/Cour reset requires independent provider-confirmed episode boundary")
        unit_key,mode,start="part:"+str(part_no),"PART",target["tvdb_episode"]
    report["batch_authorization"]={"decision":"ELIGIBLE",
                                    "reason":"PINNED_PROVIDER_CROSSREF"}
    report.setdefault("workflow",[]).append(
        {"step":"Batch authorization","decision":"ELIGIBLE",
         "reason":"PINNED_PROVIDER_CROSSREF"})
    return {"tvdb_id":tvdb,"anidb_id":anidb,"season":season,
            "title":alias,"unit_key":unit_key,"mode":mode,"start":start,
            "infohash":infohash.lower(),
            "xml_sha256":hashlib.sha256(xml_bytes).hexdigest()}


def authorize_verified_batch(db, notification_id, report, settings, xml_bytes):
    """Persist one batch lease intent and enqueue without contacting qB."""
    if db.in_transaction:
        raise ValueError("Autocommit required for trusted batch authorization")
    ensure_schema(db)
    # This authorization is exclusively for an Autobrr pack that intake has
    # classified and saved. Ordinary unmatched *single* episodes must not
    # receive misleading batch missing-magnet diagnostics.
    if not db.execute("SELECT 1 FROM anime_batch_pending WHERE notification_id=?",
                      (notification_id,)).fetchone():
        return False
    result=verified_pack_candidate(db,notification_id,report,settings,xml_bytes)
    if result is None:
        return False
    evidence="anime-lists:"+result["xml_sha256"][:32]
    record_verified_window(db,tvdb_id=result["tvdb_id"],
                           anidb_id=result["anidb_id"],season=result["season"],
                           unit_key=result["unit_key"],mode=result["mode"],
                           start_episode=result["start"],evidence_ref=evidence)
    db.execute("BEGIN IMMEDIATE")
    try:
        previous=db.execute("""SELECT tvdb_id,anidb_id,season,unit_key,title,
                                    xml_sha256,infohash
            FROM anime_batch_authorizations WHERE notification_id=?""",
            (notification_id,)).fetchone()
        values=tuple(result[k] for k in ("tvdb_id","anidb_id","season",
                     "unit_key","title","xml_sha256","infohash"))
        if previous and previous!=values:
            raise ValueError("Conflicting verified batch authorization")
        if not previous:
            db.execute("""INSERT INTO anime_batch_authorizations VALUES (?,?,?,?,?,?,?,?)""",
                       (notification_id,*values))
        existing_series=db.execute("SELECT id,status FROM series WHERE source='tvdb' AND external_id=?",
                                   (result["tvdb_id"],)).fetchone()
        if existing_series:
            if existing_series[1]=="REJECTED" or db.execute(
                "SELECT 1 FROM series_quarantine WHERE series_id=?",(existing_series[0],)).fetchone() or db.execute(
                "SELECT 1 FROM series_rejection_blocks WHERE series_id=?",(existing_series[0],)).fetchone():
                raise ValueError("Blocked or rejected verified batch series")
        else:
            db.execute("INSERT INTO series(source,external_id,title) VALUES ('tvdb',?,?)",
                       (result["tvdb_id"],result["title"]))
        from anime_async_daemon import ensure_schema as job_schema
        job_schema(db)
        payload=json.dumps({"notification_id":notification_id},sort_keys=True)
        db.execute("""INSERT OR IGNORE INTO daemon_jobs(kind,subject_key,payload_json,state)
            VALUES (?,?,?,'READY')""",(JOB_KIND,str(notification_id),payload))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    LOG.info("event=BATCH_IDENTITY_VERIFIED reason=PINNED_PROVIDER_CROSSREF "
             "notification=%d tvdb=%s season=%d hash=%s",
             notification_id,result["tvdb_id"],result["season"],result["infohash"][:12])
    return True
