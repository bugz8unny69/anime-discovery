"""Independent, episode-agnostic verified TVDB-season/AniDB identity memory.

Never authorizes an acquisition. Names are normalized without release groups.
A cache hit is only a lookup hint until fresh episode/provider validation.
"""
import hashlib
import json
import logging
import time
import xml.etree.ElementTree as ET

from anime_identification_probe import norm, release_title

LOG=logging.getLogger("anime_discovery.identity")

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS verified_season_identities (
        tvdb_id TEXT NOT NULL, season INTEGER NOT NULL, anidb_id TEXT NOT NULL,
        display_title TEXT NOT NULL, evidence_sha256 TEXT NOT NULL,
        verified_at INTEGER NOT NULL,
        PRIMARY KEY(tvdb_id,season))""")
    db.execute("""CREATE TABLE IF NOT EXISTS verified_season_aliases (
        alias_key TEXT NOT NULL, season INTEGER NOT NULL,
        tvdb_id TEXT NOT NULL,
        PRIMARY KEY(alias_key,season),
        FOREIGN KEY(tvdb_id,season) REFERENCES verified_season_identities(tvdb_id,season))""")

def _id(value):
    if type(value) not in (str,int) or not str(value).isdecimal() or int(value)<=0:
        raise ValueError("Positive provider ID required")
    return str(int(value))

def proven_season_mapping(xml_bytes,tvdb_id,season,anidb_id):
    """Require one independent Anime-Lists entry for this exact TVDB season."""
    if not isinstance(xml_bytes,bytes) or len(xml_bytes)>16*1024*1024:
        return False
    try:
        root=ET.fromstring(xml_bytes)
        if root.tag!="anime-list":
            return False
        same=[x.get("anidbid") for x in root.findall("anime")
              if x.get("tvdbid")==str(tvdb_id)
              and x.get("defaulttvdbseason")==str(season)]
        return len(same)==1 and same[0]==str(anidb_id)
    except ET.ParseError:
        return False

def remember(db,*,title,tvdb_id,anidb_id,season,evidence_sha256):
    """Remember the independent series/season identity, not an episode number.

    A conflicting pin from another season is fine. A contradictory identity
    for the same title+season fails closed rather than replacing trusted proof.
    """
    if db.in_transaction:
        raise ValueError("Identity memory requires autocommit connection")
    tid,aid=_id(tvdb_id),_id(anidb_id)
    if type(season) is not int or not 1<=season<=100:
        raise ValueError("Positive verified season required")
    if not isinstance(title,str) or not 1<=len(title.strip())<=200:
        raise ValueError("Verified title required")
    key=norm(title)
    if len(key)<3 or not key:
        raise ValueError("Unsafe normalized title")
    if not isinstance(evidence_sha256,str) or len(evidence_sha256)!=64 or any(
            c not in "0123456789abcdef" for c in evidence_sha256):
        raise ValueError("Provider evidence digest required")
    ensure_schema(db)
    existing=db.execute("SELECT anidb_id FROM verified_season_identities WHERE tvdb_id=? AND season=?",
                        (tid,season)).fetchone()
    alias=db.execute("SELECT tvdb_id FROM verified_season_aliases WHERE alias_key=? AND season=?",
                     (key,season)).fetchone()
    if (existing and existing[0]!=aid) or (alias and alias[0]!=tid):
        raise ValueError("Conflicting verified season identity requires review")
    db.execute("BEGIN IMMEDIATE")
    try:
        db.execute("""INSERT INTO verified_season_identities
            (tvdb_id,season,anidb_id,display_title,evidence_sha256,verified_at)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(tvdb_id,season) DO UPDATE SET
                evidence_sha256=excluded.evidence_sha256,
                verified_at=excluded.verified_at""",
            (tid,season,aid,title.strip(),evidence_sha256,int(time.time())))
        db.execute("""INSERT OR IGNORE INTO verified_season_aliases(alias_key,season,tvdb_id)
            VALUES (?,?,?)""",(key,season,tid))
        db.commit()
    except BaseException:
        db.rollback()
        raise
    LOG.info("event=VERIFIED_SEASON_REMEMBERED tvdb=%s anidb=%s season=%d",
             tid,aid,season)
    return {"tvdb_id":tid,"anidb_id":aid,"season":season,"title":title.strip()}

def known_for_release(db,release):
    """Exact release-title match + explicit season only; no episode heuristics."""
    from anime_batch_selection import release_scope_hint
    hint=release_scope_hint(release)
    season=hint.get("season_hint")
    if (hint.get("kind") not in ("single_episode","season_pack")
            or type(season) is not int or season<1):
        return None
    names,_episode=release_title(release)
    if not names:
        return None
    key=norm(names[0])
    ensure_schema(db)
    matches=db.execute("""SELECT s.tvdb_id,s.anidb_id,s.season,s.display_title
        FROM verified_season_aliases a JOIN verified_season_identities s
        ON s.tvdb_id=a.tvdb_id AND s.season=a.season
        WHERE a.alias_key=? AND a.season=?""",(key,season)).fetchall()
    if len(matches)!=1:
        return None
    tvdb,anidb,season,title=matches[0]
    return {"tvdb_id":tvdb,"anidb_id":anidb,"season":season,"title":title}

def _backfill_existing_verified(db,tvdb_id):
    """Rebuild identity memory from independently verified historical evidence.

    Manual approvals are deliberately excluded. A reconstructed identity is
    still only a hint and needs today's Anime-Lists mapping on reuse.
    """
    if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='unified_identity_checks'").fetchone():
        return
    rows=db.execute("""SELECT n.release_name,c.evidence_json,d.season,v.anidb_id
        FROM episode_dispatch d JOIN notifications n ON n.id=d.notification_id
        JOIN verified_series_identity v ON v.notification_id=d.notification_id
        JOIN unified_identity_checks c ON c.notification_id=d.notification_id
        WHERE v.tvdb_id=? AND c.decision='AUTO_VERIFIED'
          AND v.mapping_source='verified_identity_mapping'
          AND v.episode_identity_verified=1 AND v.eligible_for_acquisition=1""",
        (str(tvdb_id),)).fetchall()
    for release,evidence,season,aid in rows:
        try:
            report=json.loads(evidence)
            approval=report.get("approval") or {}
            pairs=report.get("matching_pairs") or []
            if (report.get("decision")!="AUTO_VERIFIED"
                    or type(season) is not int or season<1
                    or str(approval.get("tvdb_id"))!=str(tvdb_id)
                    or str(approval.get("anidb_id"))!=str(aid)
                    or approval.get("season")!=season
                    or len(pairs)!=1
                    or str(pairs[0].get("tvdb_id"))!=str(tvdb_id)
                    or str(pairs[0].get("anidb_id"))!=str(aid)):
                continue
            titles,_=release_title(release)
            if titles:
                remember(db,title=titles[0],tvdb_id=tvdb_id,anidb_id=aid,
                         season=season,evidence_sha256=hashlib.sha256(
                             evidence.encode("utf-8")).hexdigest())
        except (ValueError,TypeError,KeyError,IndexError):
            LOG.warning("event=VERIFIED_SEASON_BACKFILL_SKIPPED reason=CONFLICT_OR_INVALID_PROOF tvdb=%s",
                        tvdb_id)
    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='anime_batch_authorizations'").fetchone():
        rows=db.execute("""SELECT a.title,a.anidb_id,a.season,a.xml_sha256
            FROM anime_batch_authorizations a JOIN notifications n
            ON n.id=a.notification_id
            JOIN unified_identity_checks c ON c.notification_id=a.notification_id
            WHERE a.tvdb_id=? AND n.status='APPROVED_BATCH'
              AND c.decision='BATCH_VERIFIED'""",(str(tvdb_id),)).fetchall()
        for title,aid,season,digest in rows:
            try:
                # A batch authorization was already crosschecked against
                # provider evidence. Never synthesize an ID from the title.
                remember(db,title=title,tvdb_id=tvdb_id,anidb_id=aid,
                         season=season,evidence_sha256=digest)
            except (ValueError,TypeError):
                LOG.warning("event=VERIFIED_BATCH_BACKFILL_SKIPPED reason=CONFLICT_OR_INVALID_PROOF tvdb=%s",tvdb_id)


def for_series(db,series_id):
    """Return only independently verified stored/legacy identity records."""
    ensure_schema(db)
    series=db.execute("SELECT external_id FROM series WHERE id=? AND source='tvdb'",
                      (series_id,)).fetchone()
    if not series:
        raise ValueError("TVDB series not found")
    tid=series[0]
    _backfill_existing_verified(db,tid)
    remembered=db.execute("""SELECT season,anidb_id,display_title
        FROM verified_season_identities WHERE tvdb_id=? ORDER BY season""",(tid,)).fetchall()
    return [{"season":season,"anidb_id":aid,"title":title,"tvdb_id":tid}
            for season,aid,title in remembered]

def remember_from_report(db,release,report,xml_bytes,*,approved=None):
    """Write ONLY a fully verified monitor outcome; never a webhook hint."""
    if report.get("decision")!="AUTO_VERIFIED" or not isinstance(approved,dict):
        return None
    keys=("tvdb_id","anidb_id","season")
    if any(approved.get(k) is None for k in keys):
        return None
    ids=report.get("matching_pairs")
    if (not isinstance(ids,list) or len(ids)!=1 or
            str(ids[0].get("tvdb_id"))!=str(approved["tvdb_id"]) or
            str(ids[0].get("anidb_id"))!=str(approved["anidb_id"])):
        return None
    if not proven_season_mapping(xml_bytes,str(approved["tvdb_id"]),
                                 approved["season"],str(approved["anidb_id"])):
        return None
    titles,_=release_title(release)
    if not titles:
        return None
    return remember(db,title=titles[0],tvdb_id=approved["tvdb_id"],
                    anidb_id=approved["anidb_id"],season=approved["season"],
                    evidence_sha256=hashlib.sha256(xml_bytes).hexdigest())

def remember_from_authorized_batch(db,notification_id,xml_bytes):
    """Only post-authorization, not from an untrusted Autobrr name."""
    ensure_schema(db)
    exists=db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='anime_batch_authorizations'").fetchone()
    if not exists:
        return None
    row=db.execute("""SELECT a.title,a.tvdb_id,a.anidb_id,a.season,n.status
        FROM anime_batch_authorizations a JOIN notifications n ON n.id=a.notification_id
        WHERE a.notification_id=?""",(notification_id,)).fetchone()
    if not row or row[4]!="APPROVED_BATCH":
        return None
    title,tvdb,anidb,season,_=row
    if not proven_season_mapping(xml_bytes,tvdb,season,anidb):
        return None
    return remember(db,title=title,tvdb_id=tvdb,anidb_id=anidb,season=season,
                    evidence_sha256=hashlib.sha256(xml_bytes).hexdigest())
