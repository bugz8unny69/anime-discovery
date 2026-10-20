"""Durable read-only Sonarr reconciliation for staged Anime Discovery series.

A registered Sonarr episode is never treated as a verified equivalent copy.
All cleanup requires a separate authenticated explicit confirmation and recheck.
"""
import json
import logging
import time
from anime_sonarr import _request
from anime_sonarr_import import inspect_registered_episodes, plan_staged_imports

LOG=logging.getLogger("anime_discovery.sonarr.reconciliation")

def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS sonarr_reconciliation (
        series_id INTEGER PRIMARY KEY REFERENCES series(id),
        sonarr_id INTEGER, checked_at INTEGER NOT NULL,
        monitored INTEGER, result TEXT NOT NULL, inventory_json TEXT NOT NULL,
        alert_at INTEGER, error_reason TEXT)""")

def snapshot(db,series_id):
    ensure_schema(db)
    row=db.execute("""SELECT sonarr_id,checked_at,monitored,result,inventory_json,error_reason
        FROM sonarr_reconciliation WHERE series_id=?""",(series_id,)).fetchone()
    if not row:return None
    return {"sonarr_id":row[0],"checked_at":row[1],
            "monitored":None if row[2] is None else bool(row[2]),
            "result":row[3],"episodes":json.loads(row[4]),"error_reason":row[5]}

def check_series(db,series_id,settings,secrets,*,opener=None):
    """Read only; check exact TVDB identity and staged episodes, never import/delete."""
    ensure_schema(db)
    row=db.execute("SELECT external_id FROM series WHERE id=? AND source='tvdb'",(series_id,)).fetchone()
    if not row or not str(row[0]).isdigit():raise ValueError("Verified TVDB series required")
    plan=plan_staged_imports(db,series_id,trial_root=settings["storage"]["trial_root"],skip_missing=True)
    kwargs={} if opener is None else {"opener":opener}
    cfg=settings["sonarr"]
    entries=_request(cfg["base_url"],secrets["sonarr_api_key"],"GET","series",**kwargs)
    if not isinstance(entries,list):raise RuntimeError("Sonarr series inventory unavailable")
    found=[s for s in entries if isinstance(s,dict) and
           str(s.get("tvdbId"))==str(row[0]) and type(s.get("id")) is int]
    if len(found)>1:raise RuntimeError("Ambiguous Sonarr TVDB series")
    monitored=None
    sonarr_id=None
    episodes=[]
    if found:
        sonarr_id=found[0]["id"]
        monitored=found[0].get("monitored")
        if type(monitored) is not bool:monitored=None
        if plan:
            episodes=inspect_registered_episodes(settings,secrets,sonarr_id=sonarr_id,
                                                  plan=plan,opener=opener)
    states=[e["status"] for e in episodes]
    status=("STAGING_CLEARED" if not plan else
            "SONARR_SERIES_MISSING" if not found else
            "ALREADY_MANAGED" if states and all(s=="REGISTERED" for s in states) else
            "PARTIALLY_MANAGED" if "REGISTERED" in states and "MISSING" in states
            and "NEEDS_REVIEW" not in states else
            "MISSING_EPISODES" if states and all(s=="MISSING" for s in states) else
            "NEEDS_REVIEW")
    # Status does not authorize cleanup, and existing KEEP state is never modified.
    now=int(time.time())
    db.execute("""INSERT INTO sonarr_reconciliation
        (series_id,sonarr_id,checked_at,monitored,result,inventory_json,error_reason)
        VALUES (?,?,?,?,?,?,NULL)
        ON CONFLICT(series_id) DO UPDATE SET sonarr_id=excluded.sonarr_id,
        checked_at=excluded.checked_at,monitored=excluded.monitored,
        result=excluded.result,inventory_json=excluded.inventory_json,
        error_reason=NULL""",
        (series_id,sonarr_id,now,None if monitored is None else int(monitored),
         status,json.dumps(episodes,separators=(",",":"))))
    LOG.info("event=SONARR_RECONCILIATION series_id=%d sonarr_id=%s result=%s count=%d monitored=%s",
             series_id,sonarr_id,status,len(episodes),monitored)
    return snapshot(db,series_id)
