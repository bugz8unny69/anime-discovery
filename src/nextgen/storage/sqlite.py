"""NextGen-only SQLite persistence. No workers, web endpoints, or legacy migrations."""
import json
import sqlite3
import time

SCHEMA = """
CREATE TABLE IF NOT EXISTS webhook_events (
 event_id INTEGER PRIMARY KEY,
 source TEXT NOT NULL,
 raw_body BLOB NOT NULL,
 received_at_ms INTEGER NOT NULL,
 state TEXT NOT NULL DEFAULT 'PENDING'
  CHECK(state IN ('PENDING','RUNNING','RETRY_WAIT','IDENTIFIED','NEEDS_REVIEW')),
 attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
 next_run_at_ms INTEGER,
 lease_token TEXT,
 lease_expires_at_ms INTEGER,
 last_reason_code TEXT
);
CREATE TABLE IF NOT EXISTS event_history (
 history_id INTEGER PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES webhook_events(event_id),
 occurred_at_ms INTEGER NOT NULL,
 event_code TEXT NOT NULL,
 reason_code TEXT,
 details_json TEXT
);
CREATE TABLE IF NOT EXISTS identified_anime (
 anidb_id INTEGER PRIMARY KEY CHECK(anidb_id > 0),
 tvdb_series_id INTEGER NOT NULL CHECK(tvdb_series_id > 0),
 title TEXT NOT NULL CHECK(length(trim(title)) > 0)
);
CREATE TABLE IF NOT EXISTS identified_episodes (
 anidb_episode_id INTEGER PRIMARY KEY CHECK(anidb_episode_id > 0),
 anidb_id INTEGER NOT NULL REFERENCES identified_anime(anidb_id),
 UNIQUE(anidb_episode_id, anidb_id)
);
CREATE TABLE IF NOT EXISTS identity_results (
 result_id INTEGER PRIMARY KEY,
 event_id INTEGER NOT NULL REFERENCES webhook_events(event_id),
 anidb_id INTEGER NOT NULL REFERENCES identified_anime(anidb_id),
 schema_version INTEGER NOT NULL CHECK(schema_version=2),
 series_json TEXT NOT NULL CHECK(json_valid(series_json)),
 validated_at_ms INTEGER NOT NULL,
 UNIQUE(event_id,anidb_id),
 UNIQUE(result_id,anidb_id)
);
CREATE TABLE IF NOT EXISTS result_episode_links (
 result_id INTEGER NOT NULL,
 anidb_id INTEGER NOT NULL,
 anidb_episode_id INTEGER NOT NULL,
 PRIMARY KEY(result_id,anidb_episode_id),
 FOREIGN KEY(result_id,anidb_id) REFERENCES identity_results(result_id,anidb_id),
 FOREIGN KEY(anidb_episode_id,anidb_id)
  REFERENCES identified_episodes(anidb_episode_id,anidb_id)
);
CREATE INDEX IF NOT EXISTS idx_event_queue ON webhook_events(state,next_run_at_ms);
CREATE INDEX IF NOT EXISTS idx_event_lease ON webhook_events(state,lease_expires_at_ms);
CREATE INDEX IF NOT EXISTS idx_history_event ON event_history(event_id,history_id);
CREATE INDEX IF NOT EXISTS idx_anime_tvdb ON identified_anime(tvdb_series_id);
CREATE INDEX IF NOT EXISTS idx_episodes_anime ON identified_episodes(anidb_id);
CREATE INDEX IF NOT EXISTS idx_links_episode ON result_episode_links(anidb_episode_id);
"""

def connect(path):
    db = sqlite3.connect(path, timeout=5)
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA busy_timeout=5000")
    db.execute("PRAGMA synchronous=FULL")
    db.execute("PRAGMA journal_mode=WAL")
    return db

def initialize(db):
    db.executescript(SCHEMA)
    db.execute("PRAGMA user_version=1")

def accept_event(db, source, raw_body, received_at_ms=None):
    """Every delivery receives its own durable work record."""
    if not isinstance(source, str) or not source.strip():
        raise ValueError("source required")
    if not isinstance(raw_body, bytes):
        raise TypeError("raw_body must be bytes")
    now = int(time.time()*1000) if received_at_ms is None else received_at_ms
    with db:
        event_id = db.execute(
            "INSERT INTO webhook_events(source,raw_body,received_at_ms) VALUES(?,?,?)",
            (source,raw_body,now)).lastrowid
        db.execute(
            "INSERT INTO event_history(event_id,occurred_at_ms,event_code) VALUES(?,?,'ACCEPTED')",
            (event_id,now))
    return event_id

def save_identity(db, event_id, candidate, validated_at_ms=None):
    """Store validated AnimeSeries v2; zero episodes are allowed."""
    from src.nextgen.schema.anime_series import AnimeSeries
    validated = AnimeSeries.from_dict(candidate)
    payload = validated.to_dict()
    anime = payload["anime"]
    aid = anime["anidb_id"]
    now = int(time.time()*1000) if validated_at_ms is None else validated_at_ms
    with db:
        event = db.execute("SELECT state,lease_token,lease_expires_at_ms FROM webhook_events WHERE event_id=?", (event_id,)).fetchone()
        if event is None:
            raise ValueError("unknown event")
        existing_result = db.execute("SELECT result_id,series_json FROM identity_results WHERE event_id=? AND anidb_id=?", (event_id,aid)).fetchone()
        if existing_result is not None:
            if json.loads(existing_result[1]) != payload:
                raise ValueError("conflicting retry result")
            return existing_result[0]
        if event[0] not in ("PENDING","RUNNING","RETRY_WAIT"):
            raise ValueError("event is not eligible for identity persistence")
        if event[0] == "RUNNING":
            raise ValueError("leased work requires explicit ownership verification")
        existing = db.execute(
            "SELECT tvdb_series_id,title FROM identified_anime WHERE anidb_id=?",
            (aid,)).fetchone()
        if existing and existing[0] != anime["tvdb_series_id"]:
            raise ValueError("conflicting canonical TVDB identity")
        if existing and existing[1] != anime["title"]:
            db.execute("UPDATE identified_anime SET title=? WHERE anidb_id=?", (anime["title"],aid))
        db.execute(
            "INSERT OR IGNORE INTO identified_anime VALUES(?,?,?)",
            (aid,anime["tvdb_series_id"],anime["title"]))
        rid = db.execute(
            "INSERT INTO identity_results(event_id,anidb_id,schema_version,series_json,validated_at_ms)"
            " VALUES(?,?,?,?,?)",
            (event_id,aid,2,json.dumps(payload,sort_keys=True),now)).lastrowid
        for episode in payload["episodes"]:
            eid = episode["anidb_episode_id"]
            owner = db.execute(
                "SELECT anidb_id FROM identified_episodes WHERE anidb_episode_id=?",
                (eid,)).fetchone()
            if owner and owner[0] != aid:
                raise ValueError("episode belongs to another anime")
            db.execute(
                "INSERT OR IGNORE INTO identified_episodes VALUES(?,?)",(eid,aid))
            db.execute(
                "INSERT INTO result_episode_links VALUES(?,?,?)",(rid,aid,eid))
        db.execute("UPDATE webhook_events SET state='IDENTIFIED', next_run_at_ms=NULL, lease_token=NULL, lease_expires_at_ms=NULL, last_reason_code=NULL WHERE event_id=?", (event_id,))
        db.execute(
            "INSERT INTO event_history(event_id,occurred_at_ms,event_code)"
            " VALUES(?,?,'SERIES_IDENTIFIED')",(event_id,now))
    return rid
