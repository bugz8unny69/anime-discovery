"""NextGen-only SQLite persistence. No workers, web endpoints, or legacy migrations."""
from contextlib import contextmanager
import json
import logging
import sqlite3
import time

from src.nextgen.history import append_event_history, append_job_history, component_name, integer
from src.nextgen.diagnostics import log_history

SCHEMA = """
CREATE TABLE IF NOT EXISTS incoming_events (
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
 event_id INTEGER NOT NULL REFERENCES incoming_events(event_id),
 occurred_at_ms INTEGER NOT NULL,
 event_code TEXT NOT NULL,
 reason_code TEXT,
 details_json TEXT,
 component TEXT CHECK(component IS NULL OR component IN
  ('supervisor','intake','coordinator','worker','identity','acquisition','api'))
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
 event_id INTEGER NOT NULL REFERENCES incoming_events(event_id),
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
 event_id INTEGER REFERENCES incoming_events(event_id),
 created_by_job_id INTEGER REFERENCES jobs(job_id),
 kind TEXT NOT NULL CHECK(length(trim(kind)) > 0),
 payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
 state TEXT NOT NULL DEFAULT 'PENDING'
   CHECK(state IN ('PENDING','RUNNING','RETRY_WAIT','ON_HOLD','NEEDS_REVIEW','DONE','BLOCKED','CANCELED')),
 available_at_ms INTEGER NOT NULL,
 attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
 lease_token TEXT,
 lease_expires_at_ms INTEGER,
 last_reason_code TEXT,
 created_at_ms INTEGER NOT NULL,
 updated_at_ms INTEGER NOT NULL,
 activity_code TEXT CHECK(activity_code IS NULL OR activity_code IN
  ('DOWNLOADING','WAITING_FOR_DOWNLOAD','WAITING_FOR_SEARCH','SKIPPED_DUPLICATE')),
 CHECK(activity_code IS NULL OR
       (activity_code='DOWNLOADING' AND state IN ('RUNNING','RETRY_WAIT')) OR
       (activity_code IN ('WAITING_FOR_DOWNLOAD','WAITING_FOR_SEARCH') AND state='RETRY_WAIT') OR
       (activity_code='SKIPPED_DUPLICATE' AND state='DONE')),
 CHECK(created_by_job_id IS NULL OR created_by_job_id <> job_id),
 CHECK(state <> 'RUNNING' OR
       (lease_token IS NOT NULL AND lease_expires_at_ms IS NOT NULL))
);
CREATE INDEX IF NOT EXISTS idx_jobs_ready ON jobs(state,available_at_ms,job_id);
CREATE INDEX IF NOT EXISTS idx_jobs_expired ON jobs(state,lease_expires_at_ms);
CREATE INDEX IF NOT EXISTS idx_jobs_event ON jobs(event_id);
-- Job history is append-only operational audit, separate from incoming event_history.
CREATE TABLE IF NOT EXISTS job_history (
 history_id INTEGER PRIMARY KEY,
 job_id INTEGER NOT NULL REFERENCES jobs(job_id),
 occurred_at_ms INTEGER NOT NULL,
 event_code TEXT NOT NULL CHECK(length(trim(event_code)) > 0),
 reason_code TEXT,
 details_json TEXT CHECK(details_json IS NULL OR json_valid(details_json)),
 component TEXT CHECK(component IS NULL OR component IN
  ('supervisor','intake','coordinator','worker','identity','acquisition','api')),
 activity_code TEXT CHECK(activity_code IS NULL OR activity_code IN
  ('DOWNLOADING','WAITING_FOR_DOWNLOAD','WAITING_FOR_SEARCH','SKIPPED_DUPLICATE'))
);
CREATE INDEX IF NOT EXISTS idx_job_history_job ON job_history(job_id,history_id);
CREATE INDEX IF NOT EXISTS idx_event_queue ON incoming_events(state,next_run_at_ms);
CREATE INDEX IF NOT EXISTS idx_event_lease ON incoming_events(state,lease_expires_at_ms);
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

@contextmanager
def admitted_connection(gate):
    """New runtime operations use admission, then open/close their connection.

    For an entire job attempt, hold gate.operation() around handler execution
    instead; that admission also covers short-lived connections and heartbeats.
    Low-level connect() is retained for explicit bootstrap and offline fixtures.
    Never nest admissions or use this during exclusive migration maintenance.
    """
    with gate.operation():
        from src.nextgen.storage.migrations import _open, MigrationError, MigrationUnsupported
        try:
            db = _open(gate.database, readonly=False)
        except (OSError, sqlite3.Error):
            raise MigrationError() from None
        try:
            try:
                if db.execute("PRAGMA user_version").fetchone()[0] != 7:
                    raise MigrationUnsupported()
                db.execute("PRAGMA busy_timeout=5000")
                db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                raise MigrationError() from None
            yield db
        finally:
            db.close()


def initialize(db):
    """Initialize a *new* NextGen database at schema v7; never implicitly upgrade.

    Existing v1/v2/v3/v4/v5/v6 databases require explicit versioned SQL migrations
    before accessing v7-only storage.
    """
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 7:
        return
    if version != 0:
        raise ValueError("existing NextGen database requires versioned SQL upgrade")
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
    if present:
        raise ValueError("database has tables but no schema version; refuse implicit upgrade")
    if db.in_transaction:
        raise ValueError("initialization requires no active transaction")
    try:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=7;\nCOMMIT;")
    except BaseException:
        db.rollback()
        raise


@contextmanager
def transaction(db):
    """Own one atomic unit; reject nesting rather than committing caller work."""
    if db.in_transaction:
        raise ValueError("requires a connection outside an active transaction")
    db.execute("BEGIN IMMEDIATE")
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def _delivery(source, raw_body):
    if type(source) is not str or not source.strip():
        raise ValueError("source required")
    if type(raw_body) is not bytes:
        raise TypeError("raw_body must be bytes")


def _log(record):
    log_history(logging.getLogger("nextgen." + record.component), record)


def accept_event(db, source, raw_body, received_at_ms=None):
    """Every delivery receives its own durable work record."""
    _delivery(source, raw_body)
    now = integer(int(time.time()*1000) if received_at_ms is None else received_at_ms)
    with transaction(db):
        event_id = db.execute(
            "INSERT INTO incoming_events(source,raw_body,received_at_ms) VALUES(?,?,?)",
            (source,raw_body,now)).lastrowid
        audit = append_event_history(db, event_id=event_id, event_code="ACCEPTED",
                                     component="intake", occurred_at_ms=now)
    _log(audit)
    return event_id

def save_identity(db, event_id, candidate, validated_at_ms=None):
    """Store validated AnimeSeries v2; zero episodes are allowed."""
    from src.nextgen.schema.anime_series import AnimeSeries
    validated = AnimeSeries.from_dict(candidate)
    payload = validated.to_dict()
    anime = payload["anime"]
    aid = anime["anidb_id"]
    now = integer(int(time.time()*1000) if validated_at_ms is None else validated_at_ms)
    integer(event_id, positive=True)
    with transaction(db):
        event = db.execute("SELECT state,lease_token,lease_expires_at_ms FROM incoming_events WHERE event_id=?", (event_id,)).fetchone()
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
        db.execute("UPDATE incoming_events SET state='IDENTIFIED', next_run_at_ms=NULL, lease_token=NULL, lease_expires_at_ms=NULL, last_reason_code=NULL WHERE event_id=?", (event_id,))
        audit = append_event_history(db, event_id=event_id, event_code="SERIES_IDENTIFIED",
                                     component="identity", occurred_at_ms=now)
    _log(audit)
    return rid

def _enqueue_job(db, *, kind, payload, component, event_id=None,
                 created_by_job_id=None, available_at_ms=None):
    if not db.in_transaction:
        raise ValueError("enqueue requires an active transaction")
    component_name(component)
    if type(kind) is not str or not kind.strip():
        raise ValueError("job kind required")
    if type(payload) is not dict:
        raise ValueError("job payload must be an object")
    raw = json.dumps(payload, allow_nan=False, sort_keys=True)
    for reference in (event_id, created_by_job_id):
        if reference is not None:
            integer(reference, positive=True)
    now = int(time.time() * 1000)
    available = integer(now if available_at_ms is None else available_at_ms)
    job_id = db.execute(
        """INSERT INTO jobs(event_id,created_by_job_id,kind,payload_json,
          available_at_ms,created_at_ms,updated_at_ms)
          VALUES(?,?,?,?,?,?,?)""",
        (event_id,created_by_job_id,kind,raw,available,now,now)
    ).lastrowid
    audit = append_job_history(db, job_id=job_id, event_code="CREATED",
                               component=component, occurred_at_ms=now,
                               details={"attempt": 0})
    return job_id, audit


def enqueue_job(db, *, kind, payload, component, event_id=None,
                created_by_job_id=None, available_at_ms=None):
    """Insert independent work and CREATED audit inside an active transaction.

    No commit or logging. Caller owns rollback and may emit CREATED with event()
    after commit. Use transaction(db), or explicit BEGIN/commit/rollback.
    component is the actual creating component, not a dependency relationship.
    """
    return _enqueue_job(db, kind=kind, payload=payload, component=component,
                        event_id=event_id, created_by_job_id=created_by_job_id,
                        available_at_ms=available_at_ms)[0]


def accept_event_and_job(db, source, raw_body, *, kind, payload):
    """Commit delivery, PENDING job and both audit rows before acknowledgment."""
    _delivery(source, raw_body)
    now = int(time.time()*1000)
    with transaction(db):
        event_id = db.execute(
            "INSERT INTO incoming_events(source,raw_body,received_at_ms) VALUES(?,?,?)",
            (source,raw_body,now)).lastrowid
        event_audit = append_event_history(db, event_id=event_id, event_code="ACCEPTED",
                                          component="intake", occurred_at_ms=now)
        job_id, job_audit = _enqueue_job(db, kind=kind, payload=payload,
                                       component="intake", event_id=event_id)
    _log(event_audit)
    _log(job_audit)
    return event_id, job_id
