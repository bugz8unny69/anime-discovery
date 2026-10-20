"""Bounded, no-guessing fallback between verified-title season-pack releases.

Development-only composition, not yet registered in the running daemon.
Caller must supply trusted TVDB/AniDB series identity and a verified season.
No torrent deletion, automatic cleanup, or default-series re-identification.
"""
import re
import sqlite3
from urllib.parse import parse_qs, urlsplit

from anime_batch_selection import SelectionNeedsReview, plan_gated_first_six, release_scope_hint
from anime_identification_probe import norm, release_title
from anime_qb_manifest_intake import submit_poll_pause
from anime_qb_e01_probe import start_e01_probe
from anime_qb_ownership import OWNED, ownership, owned_now

_HASH = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", re.I)


def batch_candidates(releases, *, verified_title, season, limit=5):
    """Rank likely packs only when exact normalized series and season agree.

    Search ranking is NOT canonical identity verification. It is called
    only after the batch worker has verified that identity independently.
    """
    if (not isinstance(verified_title, str) or not norm(verified_title)
            or type(season) is not int or not 1 <= season <= 100
            or type(limit) is not int or not 1 <= limit <= 20):
        raise ValueError("Verified title, season and candidate limit required")
    if not isinstance(releases, list):
        raise ValueError("Invalid search results")
    results = {}
    for item in releases[:500]:
        if not isinstance(item, dict):
            continue
        title = item.get("title")
        if not isinstance(title, str):
            continue
        titles, _episode = release_title(title)
        if not titles or norm(titles[0]) != norm(verified_title):
            continue
        scope = release_scope_hint(title)
        if scope["kind"] != "season_pack" or scope["season_hint"] != season:
            continue
        magnet = item.get("magnetUrl") or item.get("magnet_url")
        if not isinstance(magnet, str):
            continue
        parts = urlsplit(magnet)
        xts = parse_qs(parts.query).get("xt", [])
        if parts.scheme != "magnet" or len(xts) != 1 or not xts[0].lower().startswith("urn:btih:"):
            continue
        infohash = xts[0][9:].lower()
        if not _HASH.fullmatch(infohash):
            continue
        seeders = item.get("seeders")
        seeders = seeders if type(seeders) is int and seeders >= 0 else 0
        record = {"infohash": infohash, "magnet_uri": magnet,
                  "release_name": title, "seeders": seeders}
        existing = results.get(infohash)
        if existing is None or seeders > existing["seeders"]:
            results[infohash] = record
    return sorted(results.values(), key=lambda o: (-o["seeders"], o["infohash"]))[:limit]


def _ensure_schema(db):
    db.execute("""CREATE TABLE IF NOT EXISTS batch_candidate_decisions (
        tvdb_id TEXT NOT NULL, season INTEGER NOT NULL, infohash TEXT NOT NULL,
        decision TEXT NOT NULL CHECK(decision IN ('UNMAPPABLE','PROBE_STARTED')),
        reason TEXT NOT NULL,
        PRIMARY KEY(tvdb_id, season, infohash)
    )""")


def _remember(db, tvdb_id, season, infohash, decision, reason):
    if db.in_transaction:
        raise ValueError("Autocommit SQLite required")
    db.execute("BEGIN IMMEDIATE")
    try:
        _ensure_schema(db)
        row = db.execute("""SELECT decision FROM batch_candidate_decisions
            WHERE tvdb_id=? AND season=? AND infohash=?""",
                         (tvdb_id, season, infohash)).fetchone()
        if row and row[0] != decision:
            raise ValueError("Conflicting saved candidate decision")
        db.execute("""INSERT OR IGNORE INTO batch_candidate_decisions
            VALUES (?,?,?,?,?)""",(tvdb_id,season,infohash,decision,reason[:220]))
        db.commit()
    except BaseException:
        db.rollback()
        raise


def try_batch_candidates(db, qb, releases, *, identity, season, attempts=10,
                         sleep=None, max_candidates=5):
    """Try alternate packs only when file mapping is definitively rejected.

    Metadata delay, unknown qB state, ownership uncertainty, external writes
    and transient network errors stop this iteration; they NEVER trigger
    another torrent submission. Unsupported mappings are remembered so a
    restart can move on without re-downloading the same unusable candidate.
    A batch job needs a single per-series/season lease before invoking this.
    """
    if (not isinstance(db, sqlite3.Connection) or db.in_transaction
            or not isinstance(identity, dict)
            or not isinstance(identity.get("title"), str)
            or not norm(identity["title"])
            or not str(identity.get("tvdb_id", "")).isdigit()
            or int(identity["tvdb_id"]) <= 0
            or not str(identity.get("anidb_id", "")).isdigit()
            or int(identity["anidb_id"]) <= 0):
        raise ValueError("Trusted verified series identity and SQLite connection required")
    tvdb_id = str(int(identity["tvdb_id"]))
    candidates = batch_candidates(releases, verified_title=identity["title"],
                                  season=season, limit=max_candidates)
    _ensure_schema(db)
    selected = db.execute("""SELECT infohash FROM batch_candidate_decisions
        WHERE tvdb_id=? AND season=? AND decision='PROBE_STARTED'""",
                          (tvdb_id, season)).fetchall()
    if len(selected) > 1:
        raise RuntimeError("Multiple probes for the same verified season")
    if selected:
        infohash = selected[0][0]
        # Do not start a second candidate just because the first download
        # has not yet finished or the torrent client is temporarily offline.
        if ownership(db, infohash) != OWNED or not owned_now(db, infohash, qb):
            return {"state": "DEFERRED", "reason": "Previously selected probe not currently verified",
                    "infohash": infohash}
        files = qb.torrent_files(infohash)
        plan = plan_gated_first_six(files, season=season)
        priority = {f["index"]: f.get("priority") for f in files}
        wanted = set(plan["wanted_indices"])
        if (len(priority) != len(files)
                or any(priority.get(f["index"]) != (1 if f["index"] in wanted else 0)
                       for f in files)):
            return {"state": "DEFERRED", "reason": "Previously selected probe priorities changed",
                    "infohash": infohash}
        return {"state": "PROBE_ALREADY_SELECTED", "infohash": infohash,
                "file_index": plan["wanted_indices"][0], "season": season}

    tried = 0
    for candidate in candidates:
        infohash = candidate["infohash"]
        previous = db.execute("""SELECT decision FROM batch_candidate_decisions
            WHERE tvdb_id=? AND season=? AND infohash=?""",
                              (tvdb_id, season, infohash)).fetchone()
        if previous:
            continue
        tried += 1
        options = {"attempts": attempts}
        if sleep is not None:
            options["sleep"] = sleep
            options["interval"] = 0
        acquired = submit_poll_pause(db, infohash, candidate["magnet_uri"],
                                     qb, **options)
        if acquired["state"] != "MANIFEST_READY":
            # A delayed magnet, failed ownership proof, or other non-final
            # state does not justify starting a different simultaneous torrent.
            return {"state": acquired["state"], "infohash": infohash,
                    "reason": acquired.get("reason", "Manifest not ready")}
        try:
            # Detect unsupported episode/file mapping before touching priorities.
            plan_gated_first_six(acquired["files"], season=season)
        except SelectionNeedsReview as exc:
            _remember(db, tvdb_id, season, infohash, "UNMAPPABLE", type(exc).__name__ + ": " + str(exc))
            continue
        result = start_e01_probe(db, infohash, qb, season=season,
                                 stopped_manifest=acquired)
        _remember(db, tvdb_id, season, infohash, "PROBE_STARTED", "E01-only selection verified")
        return result
    return {"state": "NO_MAPPABLE_BATCH", "candidates_checked": tried,
            "reason": "No unique E01 in eligible batches; retry later with new releases"}
