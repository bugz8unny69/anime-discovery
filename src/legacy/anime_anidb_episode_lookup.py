"""AniDB read-only episode catalog: official HTTP API -> dedicated SQLite cache.

The official AniDB HTTP API sends public metadata over plaintext HTTP. It
requires a registered client name/version but no AniDB account credentials.
One request fetches an entire anime's episode catalog. No Shoko dependency.

The global SQLite request reservation prevents parallel Anime Discovery
processes from exceeding conservative AniDB HTTP request spacing.
"""
import re
import sqlite3
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

API_URL = "http://api.anidb.net:9001/httpapi"
MAX_BYTES = 4 * 1024 * 1024
MIN_REQUEST_GAP = 10
MISSING_REFRESH_SECONDS = 86400
ERROR_BACKOFF_SECONDS = 600
MAX_EPISODES = 10000


class AniDBLookupDeferred(Exception):
    """Lookup cannot run until the shared request cooldown has expired."""
    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__("AniDB request cooldown active")


def parse_catalog(xml_bytes, aid):
    """Return verified regular episode-number/eid pairs from one AniDB anime."""
    if type(aid) is not int or aid <= 0:
        raise ValueError("Invalid AniDB anime ID")
    if not isinstance(xml_bytes, bytes) or not xml_bytes or len(xml_bytes) > MAX_BYTES:
        raise ValueError("AniDB XML empty or oversized")
    root = ET.fromstring(xml_bytes)
    if root.tag != "anime" or root.get("id") != str(aid):
        raise ValueError("AniDB anime identity mismatch")
    container = root.find("episodes")
    if container is None:
        raise ValueError("AniDB episode list missing")
    episodes = {}
    eids = set()
    for item in container.findall("episode"):
        no = item.find("epno")
        if no is None or no.get("type") != "1":
            continue
        raw = (no.text or "").strip()
        eid = item.get("id")
        if (not raw.isascii() or not raw.isdecimal() or int(raw) <= 0 or
                eid is None or not eid.isascii() or not eid.isdecimal() or int(eid) <= 0):
            raise ValueError("Malformed regular AniDB episode identity")
        epno, internal_id = int(raw), int(eid)
        if epno in episodes or internal_id in eids:
            raise ValueError("Duplicate AniDB episode identity")
        episodes[epno] = internal_id
        eids.add(internal_id)
        if len(episodes) > MAX_EPISODES:
            raise ValueError("AniDB episode catalog too large")
    return episodes


def parse_episode_id(xml_bytes, aid, epno):
    """Backwards-compatible exact single-episode parser for offline tests."""
    if type(epno) is not int or epno <= 0:
        raise ValueError("Invalid AniDB episode number")
    return parse_catalog(xml_bytes, aid).get(epno)


def ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS anidb_anime_catalog (
        anidb_id INTEGER PRIMARY KEY CHECK(anidb_id > 0),
        fetched_at INTEGER NOT NULL CHECK(fetched_at >= 0),
        regular_episode_count INTEGER NOT NULL CHECK(regular_episode_count >= 0)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS anidb_episode_catalog (
        anidb_id INTEGER NOT NULL REFERENCES anidb_anime_catalog(anidb_id),
        episode_type INTEGER NOT NULL DEFAULT 1 CHECK(episode_type = 1),
        episode_number INTEGER NOT NULL CHECK(episode_number > 0),
        anidb_episode_id INTEGER NOT NULL CHECK(anidb_episode_id > 0),
        PRIMARY KEY (anidb_id, episode_type, episode_number),
        UNIQUE (anidb_id, anidb_episode_id)
    )""")
    db.execute("""CREATE TABLE IF NOT EXISTS anidb_http_rate_limit (
        id INTEGER PRIMARY KEY CHECK(id = 1),
        next_allowed_at INTEGER NOT NULL CHECK(next_allowed_at >= 0)
    )""")
    db.execute("INSERT OR IGNORE INTO anidb_http_rate_limit VALUES (1,0)")


def lookup_episode_id(aid, epno, *, client, clientver, metadata_path,
                      now=None, opener=urllib.request.urlopen):
    """Find exact AniDB eid. Populate entire anime once, refreshing on a miss.

    Positive IDs remain locally cached. A missing number causes at most one
    re-fetch per 24h. All callers share the SQLite request reservation.
    """
    if type(aid) is not int or aid <= 0 or type(epno) is not int or epno <= 0:
        raise ValueError("Positive AniDB anime ID and episode number required")
    if not isinstance(client, str) or not re.fullmatch(r"[A-Za-z0-9_-]{3,32}", client):
        raise ValueError("Registered AniDB HTTP client name required")
    if type(clientver) is not int or not 1 <= clientver <= 999999:
        raise ValueError("AniDB HTTP client version invalid")
    stamp = int(time.time() if now is None else now)
    db_path = Path(metadata_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path, timeout=15, isolation_level=None) as db:
        db.execute("PRAGMA busy_timeout=15000")
        db.execute("PRAGMA foreign_keys=ON")
        ensure_schema(db)
        cached = db.execute("""SELECT anidb_episode_id FROM anidb_episode_catalog
            WHERE anidb_id=? AND episode_type=1 AND episode_number=?""",
            (aid,epno)).fetchone()
        if cached is not None:
            return cached[0]
        catalog = db.execute("SELECT fetched_at FROM anidb_anime_catalog WHERE anidb_id=?",
                             (aid,)).fetchone()
        if catalog and stamp - catalog[0] < MISSING_REFRESH_SECONDS:
            return None

        # Reserve an upstream request across all processes BEFORE contacting AniDB.
        # This is a short transaction; no network I/O is done while holding it.
        db.execute("BEGIN IMMEDIATE")
        try:
            next_at = db.execute("SELECT next_allowed_at FROM anidb_http_rate_limit WHERE id=1").fetchone()[0]
            if stamp < next_at:
                raise AniDBLookupDeferred(next_at-stamp)
            db.execute("UPDATE anidb_http_rate_limit SET next_allowed_at=? WHERE id=1",
                       (stamp+MIN_REQUEST_GAP,))
            db.commit()
        except BaseException:
            db.rollback()
            raise

        args = urllib.parse.urlencode({"request":"anime", "aid":aid, "protover":1,
                                       "client":client, "clientver":clientver})
        request = urllib.request.Request(API_URL + "?" + args,
            headers={"User-Agent":"AnimeDiscovery/1.0","Accept":"application/xml"})
        try:
            with opener(request, timeout=30) as response:
                raw = response.read(MAX_BYTES+1)
            episodes = parse_catalog(raw, aid)
        except Exception:
            # Slow subsequent requests after server errors, timeouts or invalid XML.
            db.execute("BEGIN IMMEDIATE")
            try:
                db.execute("""UPDATE anidb_http_rate_limit
                    SET next_allowed_at=MAX(next_allowed_at,?) WHERE id=1""",
                    (stamp+ERROR_BACKOFF_SECONDS,))
                db.commit()
            except BaseException:
                db.rollback()
                raise
            raise
        db.execute("BEGIN IMMEDIATE")
        try:
            db.execute("""INSERT INTO anidb_anime_catalog(anidb_id,fetched_at,regular_episode_count)
                VALUES (?,?,?) ON CONFLICT(anidb_id) DO UPDATE SET
                fetched_at=excluded.fetched_at,
                regular_episode_count=excluded.regular_episode_count""",
                (aid,stamp,len(episodes)))
            db.execute("DELETE FROM anidb_episode_catalog WHERE anidb_id=?", (aid,))
            db.executemany("""INSERT INTO anidb_episode_catalog
                (anidb_id,episode_type,episode_number,anidb_episode_id)
                VALUES (?,1,?,?)""", [(aid,no,eid) for no,eid in episodes.items()])
            db.commit()
        except BaseException:
            db.rollback()
            raise
        return episodes.get(epno)
