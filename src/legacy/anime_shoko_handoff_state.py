"""Persist Shoko reconciliation for Anime Discovery-originated Sonarr imports.

Explicit trusted AniDB *episode* mappings are required. TVDB series identity
and season/episode alone never authorize an AniDB association. No HTTP writes.
"""
import json

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS shoko_handoff (
        series_id INTEGER NOT NULL,
        notification_id INTEGER NOT NULL,
        destination TEXT NOT NULL,
        anidb_episode_id INTEGER,
        identity_verified INTEGER NOT NULL DEFAULT 0,
        status TEXT NOT NULL DEFAULT 'NEEDS_EPISODE_IDENTITY',
        observation_json TEXT,
        PRIMARY KEY (series_id,notification_id)
    )""")

def record_verified_episode(db,*,series_id,notification_id,anidb_episode_id):
    """Record independently verified AniDB episode ID, never a guessed mapping."""
    if any(type(x) is not int or x<=0 for x in
           (series_id,notification_id,anidb_episode_id)):
        raise ValueError("Positive exact IDs required")
    ensure_schema(db)
    row=db.execute("""SELECT status FROM shoko_handoff
                      WHERE series_id=? AND notification_id=?""",
                   (series_id,notification_id)).fetchone()
    if row is None:
        raise ValueError("Sonarr import provenance missing")
    if row[0] not in ('NEEDS_EPISODE_IDENTITY','AWAITING_SHOKO_SCAN',
                      'UNRECOGNIZED_NEEDS_REVIEW','SHOKO_API_ERROR'):
        raise ValueError("Identity mapping change requires explicit review")
    db.execute("""UPDATE shoko_handoff SET anidb_episode_id=?,
               identity_verified=1,status='AWAITING_SHOKO_SCAN',
               observation_json=NULL WHERE series_id=? AND notification_id=?""",
               (anidb_episode_id,series_id,notification_id))

def enqueue_verified_copies(db,series_id,manifest,destinations):
    """Persist exact Sonarr destinations after independent hash verification."""
    if len(manifest)!=len(destinations) or not manifest:
        raise ValueError("Import manifest/destination mismatch")
    ensure_schema(db)
    for item,destination in zip(manifest,destinations):
        nid=item.get("notification_id")
        if type(nid) is not int or nid<=0 or not isinstance(destination,str) or not destination:
            raise ValueError("Invalid Sonarr provenance")
        existing=db.execute("""SELECT destination FROM shoko_handoff
                          WHERE series_id=? AND notification_id=?""",
                            (series_id,nid)).fetchone()
        if existing and existing[0]!=destination:
            raise RuntimeError("Sonarr destination changed; manual review required")
        db.execute("""INSERT OR IGNORE INTO shoko_handoff
                    (series_id,notification_id,destination)
                    VALUES (?,?,?)""",(series_id,nid,destination))

def reconcile_one(db,settings,secrets,*,series_id,notification_id,inspector=None):
    """Perform read-only Shoko observation and retain status for retry."""
    ensure_schema(db)
    row=db.execute("""SELECT destination,anidb_episode_id,identity_verified
                    FROM shoko_handoff WHERE series_id=? AND notification_id=?""",
                    (series_id,notification_id)).fetchone()
    if row is None:
        raise ValueError("No Anime Discovery handoff record")
    if inspector is None:
        from anime_shoko_handoff import inspect_imported_episode
        inspector=inspect_imported_episode
    result=inspector(settings["shoko"]["base_url"],secrets["shoko_api_key"],
        destination=row[0],sonarr_root=settings["sonarr"]["root_folder"],
        anidb_episode_id=row[1],verified_episode_identity=(row[2]==1))
    if not isinstance(result,dict) or result.get("writes_enabled") is not False:
        raise RuntimeError("Unsafe Shoko observation")
    valid={'NEEDS_EPISODE_IDENTITY','AWAITING_SHOKO_SCAN',
           'AMBIGUOUS_SHOKO_FILE','UNRECOGNIZED_NEEDS_REVIEW',
           'SHOKO_ALREADY_LINKED','LINK_PLAN_READY',
           'SHOKO_ALREADY_LINKED_VERIFIED','SHOKO_LINK_VERIFIED',
           'CONFLICTING_SHOKO_LINK','AMBIGUOUS_SHOKO_LINK'}
    status=result.get("status")
    if status not in valid:
        raise RuntimeError("Unexpected Shoko observation status")
    db.execute("""UPDATE shoko_handoff SET status=?,observation_json=?
               WHERE series_id=? AND notification_id=?""",
               (status,json.dumps(result,sort_keys=True),series_id,notification_id))
    return result
