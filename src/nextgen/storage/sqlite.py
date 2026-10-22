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

-- Jobs are independent units of work, not a parent/child dependency graph.
-- created_by_job_id is optional provenance only.
CREATE TABLE IF NOT EXISTS jobs (
 job_id INTEGER PRIMARY KEY,
 event_id INTEGER REFERENCES webhook_events(event_id),
 created_by_job_id INTEGER REFERENCES jobs(job_id),
 kind TEXT NOT NULL CHECK(length(trim(kind)) > 0),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 state TEXT NOT NULL DEFAULT 'PENDING'
   CHECK(state IN ('PENDING','RUNNING','RETRY_WAIT','NEEDS_REVIEW','DONE')),
 available_at_ms INTEGER NOT NULL,
 attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
 lease_token TEXT,
 lease_expires_at_ms INTEGER,
 last_reason_code TEXT,
 created_at_ms INTEGER NOT NULL,
 updated_at_ms INTEGER NOT NULL,
 CHECK(created_by_job_id IS NULL OR created_by_job_id <> job_id),
 CHECK(state <> 'RUNNING' OR
       (lease_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(state,available_at_ms,job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_expired ON jobs(state,lease_expires_at_ms);
CREATE INDEX IF NOT EXISTS idx_jobs_event ON jobs(event_id);
-- Job history is append-only operational audit, separate from webhook event_history.
CREATE TABLE IF NOT EXISTS job_history (
 history_id INTEGER PRIMARY KEY,
 job_id INTEGER NOT NULL REFERENCES jobs(job_id),
 occurred_at_ms INTEGER NOT NULL,
 event_code TEXT NOT NULL CHECK(length(trim(event_code)) > 0),
 reason_code TEXT,
 details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json))
);
CREATE INDEX IF NOT EXISTS idx_job_history_job ON job_history(job_id,history_id);
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
    """Initialize a *new* NextGen database at schema v2; never downgrade an existing file.

    Existing v1 databases must apply sql/002_independent_jobs.sql via the
    future version-aware migration runner before accessing v2-only storage.
    """
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 2:
        return
    if version != 0:
        raise ValueError("existing NextGen database requires versioned SQL upgrade")
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
    if present:
        raise ValueError("database has tables but no schema version; refuse implicit upgrade")
    db.executescript(SCHEMA)
    db.execute("PRAGMA user_version=2")

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

def enqueue_job(db, *, kind, payload, event_id=None, created_by_job_id=None,
                available_at_ms=None):
    """Add independent work within a caller-controlled transaction if present.

    The caller can atomically insert a successor and mark its predecessor DONE.
    This helper deliberately does not commit and does not implement dispatch.
    """
    if not isinstance(kind, str) or not kind.strip():
        raise ValueError("job kind required")
    raw = json.dumps(payload, allow_nan=False, sort_keys=True)
    if not isinstance(payload, dict):
        raise ValueError("job payload must be an object")
    now = int(time.time() * 1000)
    available = now if available_at_ms is None else available_at_ms
    return db.execute(
        """INSERT INTO jobs(event_id,created_by_job_id,kind,payload_json,
          available_at_ms,created_at_ms,updated_at_ms)
          VALUES(?,?,?,?,?,?,?)""",
        (event_id,created_by_job_id,kind,raw,available,now,now)
    ).lastrowid


def accept_event_and_job(db, source, raw_body, *, kind, payload):
    """Commit delivery, PENDING job and audit row together before acknowledgment."""
    if db.in_transaction:
        raise ValueError("requires a connection outside an active transaction")
    with db:
        event_id = db.execute(
            "INSERT INTO webhook_events(source,raw_body,received_at_ms) VALUES(?,?,?)",
            (source,raw_body,int(time.time()*1000))).lastrowid
        job_id = enqueue_job(db,kind=kind,payload=payload,event_id=event_id)
        db.execute(
            "INSERT INTO event_history(event_id,occurred_at_ms,event_code) VALUES(?,?,'ACCEPTED')",
            (event_id,int(time.time()*1000)))
    return event_id, job_id
