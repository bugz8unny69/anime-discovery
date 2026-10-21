"""AniDB read-only episode catalog: official HTTP API -> dedicated SQLite cache.

The official AniDB HTTP API sends public metadata over plaintext HTTP. It
requires a registered client name/version but no AniDB account credentials.
One request fetches an entire anime's episode catalog. No Shoko dependency.

The global SQLite request reservation prevents parallel Anime Discovery
processes from exceeding conservative AniDB HTTP request spacing.
"""
import gzip
import io
import logging
import re
import zlib
import sqlite3
import time
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from anime_xml_response_diagnostics import InvalidXMLResponse,log_bad_xml

API_URL = "http://api.anidb.net:9001/httpapi"
MAX_BYTES = 4 * 1024 * 1024
MIN_REQUEST_GAP = 10
MISSING_REFRESH_SECONDS = 86400
ERROR_BACKOFF_SECONDS = 600
MAX_EPISODES = 10000
LOG = logging.getLogger(__name__)


class AniDBLookupDeferred(Exception):
    """Lookup cannot run until the shared request cooldown has expired."""
    def __init__(self, retry_after_seconds):
        self.retry_after_seconds = max(1, int(retry_after_seconds))
        super().__init__("AniDB request cooldown active")



def decode_episode_xml(payload, *, encoding=None):
    """Decode HTTP content coding before XML parse; bound decompressed bytes.

    AniDB's HTTP API can send gzip-compressed XML with Content-Type text/xml.
    urllib.request does not transparently decode HTTP Content-Encoding.
    For legacy/misconfigured upstreams, recognize gzip or zlib magic even
    when Content-Encoding is absent. Never silently accept unknown encodings.
    """
    if not isinstance(payload, bytes) or not payload or len(payload) > MAX_BYTES:
        raise ValueError("Invalid AniDB HTTP response size")
    codec=(encoding or "").strip().lower()
    if codec in ("", "identity"):
        if payload.startswith(b"\x1f\x8b"):
            codec="gzip"
        elif (len(payload)>=2 and payload[0]&15==8 and
              (payload[0]*256+payload[1])%31==0):
            codec="deflate"
        else:
            return payload,"identity"
    try:
        if codec in ("gzip","x-gzip"):
            with gzip.GzipFile(fileobj=io.BytesIO(payload)) as stream:
                plain=stream.read(MAX_BYTES+1)
            codec="gzip"
        elif codec=="deflate":
            decoder=zlib.decompressobj()
            plain=decoder.decompress(payload,MAX_BYTES+1)
            if decoder.unconsumed_tail or not decoder.eof or decoder.unused_data:
                raise ValueError("Invalid or oversized deflate response")
        else:
            raise ValueError("Unsupported AniDB response encoding")
    except (OSError,EOFError,zlib.error) as exc:
        raise ValueError("Malformed compressed AniDB HTTP response") from None
    if not plain or len(plain)>MAX_BYTES:
        raise ValueError("Invalid or oversized decompressed AniDB response")
    return plain,codec


def _anidb_error_code(xml_bytes):
    """Extract bounded public AniDB error code, never return response text."""
    try:
        root=ET.fromstring(xml_bytes)
    except ET.ParseError:
        return None
    if root.tag!="error":
        return None
    code=root.get("code") or "UNKNOWN"
    return code if re.fullmatch(r"[A-Za-z0-9_-]{1,16}",code) else "UNKNOWN"

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
        # A positive cache entry must belong to an existing validated
        # per-anime catalog. Never trust an orphaned/internally inconsistent
        # SQLite row as an AniDB EID.
        cached = db.execute("""SELECT e.anidb_episode_id, a.fetched_at,
                    a.regular_episode_count
            FROM anidb_episode_catalog AS e
            LEFT JOIN anidb_anime_catalog AS a ON a.anidb_id=e.anidb_id
            WHERE e.anidb_id=? AND e.episode_type=1 AND e.episode_number=?""",
            (aid,epno)).fetchone()
        if cached is not None:
            eid, fetched_at, episode_count = cached
            if (type(eid) is not int or eid<=0 or
                    type(fetched_at) is not int or fetched_at<0 or
                    type(episode_count) is not int or episode_count<1):
                raise ValueError("Unverified AniDB episode cache identity")
            return eid
        catalog = db.execute("SELECT fetched_at, regular_episode_count FROM anidb_anime_catalog WHERE anidb_id=?",
                             (aid,)).fetchone()
        if catalog and (type(catalog[0]) is not int or catalog[0]<0 or
                        type(catalog[1]) is not int or catalog[1]<0):
            raise ValueError("Invalid AniDB catalog cache metadata")
        # Clock rollback must not indefinitely suppress lookup of a missing
        # episode; require a nonnegative cache age for the negative TTL.
        if catalog and 0<=stamp-catalog[0]<MISSING_REFRESH_SECONDS:
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
            headers={"User-Agent":"AnimeDiscovery/1.0","Accept":"application/xml",
                     "Accept-Encoding":"gzip, deflate"})
        try:
            status=None
            content_type=None
            content_encoding=None
            try:
                with opener(request, timeout=30) as response:
                    status=getattr(response,"status",None)
                    headers=getattr(response,"headers",None)
                    content_type=headers.get("Content-Type") if headers else None
                    content_encoding=headers.get("Content-Encoding") if headers else None
                    raw=response.read(MAX_BYTES+1)
            except urllib.error.HTTPError as failure:
                raw=failure.read(160)
                log_bad_xml("ANIDB_EPISODE_HTTP",raw,status=failure.code,
                            content_type=failure.headers.get("Content-Type"),
                            reason="HTTP_ERROR")
                raise InvalidXMLResponse("ANIDB_EPISODE_HTTP","HTTP_ERROR") from None
            if status is not None and status!=200:
                log_bad_xml("ANIDB_EPISODE_HTTP",raw,status=status,
                            content_type=content_type,reason="HTTP_STATUS")
                raise InvalidXMLResponse("ANIDB_EPISODE_HTTP","HTTP_STATUS")
            try:
                plain,codec=decode_episode_xml(raw,encoding=content_encoding)
            except ValueError as failure:
                log_bad_xml("ANIDB_EPISODE_HTTP",raw,status=status,
                            content_type=content_type,
                            content_encoding=content_encoding,
                            reason="DECODE_"+type(failure).__name__)
                raise InvalidXMLResponse("ANIDB_EPISODE_HTTP","DECODE_FAILED") from None
            try:
                episodes=parse_catalog(plain,aid)
            except (ET.ParseError,ValueError) as failure:
                api_error=_anidb_error_code(plain)
                kind=("ANIDB_ERROR_"+api_error if api_error
                      else type(failure).__name__)
                log_bad_xml("ANIDB_EPISODE_HTTP",plain,status=status,
                            content_type=content_type,content_encoding=codec,
                            encoded_bytes=len(raw),reason=kind)
                raise InvalidXMLResponse("ANIDB_EPISODE_HTTP",kind) from None
            LOG.info("AniDB episode catalog validated anidb_id=%s regular_episodes=%s "
                     "content_encoding=%s compressed_bytes=%s decoded_bytes=%s",
                     aid,len(episodes),codec,len(raw),len(plain))
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
