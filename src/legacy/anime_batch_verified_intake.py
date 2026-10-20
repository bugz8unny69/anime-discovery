"""Authorize an Autobrr season pack only after independent provider identity triage.

Called from the existing identity monitor, NEVER from a webhook-provided pair.
Requires admin-pinned series alias/season, single TVDB/AniDB cross-reference,
independent Anime-Lists pair corroboration, and exact incoming torrent hash.
Episode numbers and file sizes are still verified after qB metadata arrives.
"""
import hashlib
import json
import logging

from anime_batch_selection import release_scope_hint
from anime_identity_mapping_v4 import mappings
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
    """Return pinned identity info or None; never infer ID from release text."""
    if not isinstance(report, dict) or not isinstance(settings, dict):
        return None
    if not isinstance(xml_bytes,bytes) or not xml_bytes:
        return None
    row=db.execute("""SELECT n.release_name,n.info_hash,n.source,p.magnet_uri
        FROM notifications n JOIN anime_batch_pending p ON p.notification_id=n.id
        WHERE n.id=?""",(notification_id,)).fetchone()
    if not row or row[2] != "autobrr":
        return None
    title,infohash,_source,_magnet=row
    hint=release_scope_hint(title)
    season=hint.get("season_hint")
    if hint["kind"]!="season_pack" or type(season) is not int or season<=0:
        return None
    names,_=release_title(title)
    if not names:
        return None
    aliases=settings.get("identity",{}).get("series_map",{})
    if not isinstance(aliases,dict):
        return None
    matches=[(alias,identity) for alias,identity in aliases.items()
             if norm(alias)==norm(names[0])
             and isinstance(identity,dict) and identity.get("season",1)==season]
    if len(matches)!=1:
        return None
    alias,identity=matches[0]
    try:
        tvdb=str(int(identity["tvdb_id"]))
        anidb=str(int(identity["anidb_id"]))
    except (KeyError, ValueError, TypeError):
        return None
    if tvdb=="0" or anidb=="0":
        return None
    pairs=report.get("matching_pairs")
    if (not isinstance(pairs,list) or len(pairs)!=1 or
            str(pairs[0].get("tvdb_id"))!=tvdb or
            str(pairs[0].get("anidb_id"))!=anidb):
        return None
    # A genuine episode-missing season pack has precisely these expected
    # issues; no title ambiguity, conflicting provider identity or unsupported
    # media type may be present.
    issues=set(report.get("issues") or [])
    expected={"BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED",
              "EXACT_IDENTITY_NOT_VERIFIED"}
    if not {"BATCH_FILE_MANIFEST_REQUIRED","EPISODE_NUMBER_UNRESOLVED"}.issubset(issues) or issues-expected:
        return None
    diagnostic=[r for r in report.get("crossref_diagnostics",[])
                if str(r.get("tvdb_id"))==tvdb]
    if (len(diagnostic)!=1 or diagnostic[0].get("media_type")!="ANIMATION"
            or anidb not in [str(n) for n in diagnostic[0].get("matching_anidb_ids",[])]):
        return None
    # Authenticate a unique actual pair from the independent XML source.
    try:
        mapped=mappings(xml_bytes,anidb)
    except Exception:
        return None
    if len(mapped)!=1 or mapped[0].get("tvdbid")!=tvdb:
        return None
    return {"tvdb_id":tvdb,"anidb_id":anidb,"season":season,
            "title":alias,"unit_key":"season","infohash":infohash.lower(),
            "xml_sha256":hashlib.sha256(xml_bytes).hexdigest()}


def authorize_verified_batch(db, notification_id, report, settings, xml_bytes):
    """Persist one batch lease intent and enqueue without contacting qB."""
    if db.in_transaction:
        raise ValueError("Autocommit required for trusted batch authorization")
    ensure_schema(db)
    result=verified_pack_candidate(db,notification_id,report,settings,xml_bytes)
    if result is None:
        return False
    evidence="anime-lists:"+result["xml_sha256"][:32]
    record_verified_window(db,tvdb_id=result["tvdb_id"],
                           anidb_id=result["anidb_id"],season=result["season"],
                           unit_key=result["unit_key"],mode="SEASON",
                           start_episode=1,evidence_ref=evidence)
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
