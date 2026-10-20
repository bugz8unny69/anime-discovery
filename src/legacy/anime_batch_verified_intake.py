"""Authorize an Autobrr season pack only after independent provider identity triage.

Called from the existing identity monitor, NEVER from a webhook-provided pair.
Requires a uniquely title-verified TVDB series, season-matched independent
Anime-Lists AniDB mapping, and exact incoming torrent hash. Recognized Names
pins are optional constraints, never a prerequisite for automatic discovery.
Episode numbers and file sizes are still verified after qB metadata arrives.
"""
import hashlib
import json
import logging
import re
import xml.etree.ElementTree as ET

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
    # source names the originating indexer/feed (e.g. nyaa), not the
    # authenticated Autobrr transport. The pending intake is the gate.
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
    # The release's title was already checked against an exact AniDB title,
    # TheTVDB titles and one independently corroborated TVDB/AniDB crossref.
    # AniDB creates a different anime ID for subsequent seasons whereas TVDB
    # may put them in the same series. Choose the correct *season's* AniDB ID
    # from trusted Anime-Lists rather than reusing the title-matched S01 ID.
    pairs=report.get("matching_pairs")
    if not isinstance(pairs,list) or len(pairs)!=1:
        return blocked("BATCH_PROVIDER_PAIR_NOT_UNIQUE",
                       "Require one independently verified TVDB series before examining season mapping")
    pair=pairs[0]
    tvdb=str(pair.get("tvdb_id"))
    initial_anidb=str(pair.get("anidb_id"))
    if not tvdb.isdecimal() or not initial_anidb.isdecimal():
        return blocked("BATCH_PROVIDER_PAIR_INVALID",
                       "Invalid AniDB/TVDB identity returned by provider verification")
    diagnostics=[r for r in report.get("crossref_diagnostics",[])
                 if str(r.get("tvdb_id"))==tvdb]
    if (len(diagnostics)!=1 or diagnostics[0].get("media_type")!="ANIMATION"
            or initial_anidb not in
            [str(aid) for aid in diagnostics[0].get("matching_anidb_ids",[])]):
        return blocked("BATCH_ANIMATION_CROSSREF_UNVERIFIED",
                       "TheTVDB animated series and original AniDB title must have independent corroboration")
    issues=set(report.get("issues") or [])
    expected={"BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED",
              "EXACT_IDENTITY_NOT_VERIFIED"}
    if not {"BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED"}.issubset(issues) or issues-expected:
        return blocked("BATCH_OTHER_IDENTITY_ISSUES",
                       "Resolve conflicting provider, media type or episode evidence before downloading")
    # Assert the original title-matched AniDB record actually belongs to
    # the matched TVDB series. Then search the entire mapping for a unique
    # record of that *TVDB season*. These are not necessarily the same AniDB ID.
    try:
        root=ET.fromstring(xml_bytes)
        if root.tag!="anime-list":
            raise ValueError("Unexpected Anime-Lists XML root")
        anchor=[node for node in root.findall("anime")
                if node.get("anidbid")==initial_anidb]
        if len(anchor)!=1 or anchor[0].get("tvdbid")!=tvdb:
            return blocked("BATCH_ORIGINAL_TITLE_PAIR_UNCORROBORATED",
                           "The title-matched AniDB entry is not independently linked to this TVDB series")
        same_season=[node for node in root.findall("anime")
                     if node.get("tvdbid")==tvdb
                     and node.get("defaulttvdbseason")==str(season)
                     and (node.get("anidbid") or "").isdecimal()
                     and int(node.get("anidbid"))>0]
    except (ET.ParseError,ValueError,TypeError):
        return blocked("BATCH_ANIME_LISTS_MAPPING_UNREADABLE",
                       "The trusted Anime-Lists source cannot be parsed safely")
    if len(same_season)!=1:
        return blocked("BATCH_SEASON_MAPPING_UNAVAILABLE" if not same_season
                       else "BATCH_SEASON_MAPPING_AMBIGUOUS",
                       "Anime-Lists must uniquely map this TVDB series and its release season to an AniDB production")
    anidb=same_season[0].get("anidbid")
    # Pins help disambiguate release naming, but are not required for correct
    # independent provider identification. A contradictory explicit pin must
    # not silently override the verified Anime-Lists season-specific result.
    aliases=settings.get("identity",{}).get("series_map",{})
    if not isinstance(aliases,dict):
        return blocked("BATCH_PINNED_ALIASES_INVALID",
                       "Recognized Names must be a mapping when configured")
    title_matches=[(alias,identity) for alias,identity in aliases.items()
                   if norm(alias)==norm(names[0]) and isinstance(identity,dict)
                   and identity.get("season",1)==season]
    if len(title_matches)>1:
        return blocked("BATCH_PINNED_ALIAS_AMBIGUOUS",
                       "Multiple Recognized Names entries conflict for this season")
    alias=names[0]
    if title_matches:
        alias,identity=title_matches[0]
        try:
            pinned_tvdb=str(int(identity["tvdb_id"]))
            pinned_anidb=str(int(identity["anidb_id"]))
        except (KeyError,ValueError,TypeError):
            return blocked("BATCH_PINNED_IDS_INVALID",
                           "Correct the explicitly configured TVDB/AniDB IDs")
        if (pinned_tvdb,pinned_anidb)!=(tvdb,anidb):
            return blocked("BATCH_PINNED_PROVIDER_PAIR_MISMATCH",
                           "Recognized Names must agree with the Anime-Lists season-specific TVDB/AniDB mapping")
    report["batch_season_mapping"]={"tvdb_id":tvdb,"anidb_id":anidb,
                                    "season":season,"initial_anidb_id":initial_anidb,
                                    "source":"Anime-Lists"}
    LOG.info("event=BATCH_SEASON_MAPPING notification=%d tvdb=%s season=%d "
             "anidb=%s title_matched_anidb=%s source=Anime-Lists",
             notification_id,tvdb,season,anidb,initial_anidb)
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
                                    "reason":"SEASON_SPECIFIC_ANIME_LISTS_CROSSREF"}
    report.setdefault("workflow",[]).append(
        {"step":"Batch authorization","decision":"ELIGIBLE",
         "reason":"SEASON_SPECIFIC_ANIME_LISTS_CROSSREF"})
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
        # The old implementation silently skipped legitimate indexer-labelled
        # packs, hiding the actual blocker behind episode-missing diagnostics.
        row=db.execute("SELECT release_name FROM notifications WHERE id=?",
                       (notification_id,)).fetchone()
        if row and release_scope_hint(row[0])["kind"]=="season_pack":
            report["batch_authorization"]={"decision":"BLOCKED",
                "reason":"BATCH_PENDING_MAGNET_MISSING",
                "action":"Resubmit the original authenticated webhook with its validated magnet and recheck identity"}
            report["issues"]=["BATCH_PENDING_MAGNET_MISSING"]+[
                issue for issue in report.get("issues",[])
                if issue!="BATCH_PENDING_MAGNET_MISSING"]
            report.setdefault("workflow",[]).append({"step":"Batch authorization",
                "decision":"BLOCKED","reason":"BATCH_PENDING_MAGNET_MISSING"})
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
    LOG.info("event=BATCH_IDENTITY_VERIFIED reason=SEASON_SPECIFIC_ANIME_LISTS_CROSSREF "
             "notification=%d tvdb=%s anidb=%s season=%d hash=%s",
             notification_id,result["tvdb_id"],result["anidb_id"],
             result["season"],result["infohash"][:12])
    return True
