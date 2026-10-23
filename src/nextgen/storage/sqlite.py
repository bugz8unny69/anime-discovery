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
  ('DOWNLOADING','WAITING_FOR_DOWNLOAD','WAITING_FOR_SEARCH','SKIPPED_DUPLICATE')),
 handler_code TEXT,
 handler_label TEXT,
 invocation_id TEXT,
 CHECK((handler_code IS NULL AND handler_label IS NULL AND invocation_id IS NULL) OR
       (handler_code IS NOT NULL AND handler_label IS NOT NULL AND invocation_id IS NOT NULL
        AND length(handler_code) BETWEEN 1 AND 64 AND handler_code GLOB '[A-Z]*'
        AND handler_code NOT GLOB '*[^A-Z0-9_]*'
        AND length(handler_label) BETWEEN 1 AND 128 AND length(trim(handler_label)) > 0
        AND length(invocation_id)=32 AND invocation_id NOT GLOB '*[^a-f0-9]*'))
);
CREATE INDEX IF NOT EXISTS idx_job_history_invocation ON job_history(invocation_id,history_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_handler_invocation_start ON job_history(invocation_id)
 WHERE event_code='HANDLER_STARTED';
CREATE UNIQUE INDEX IF NOT EXISTS idx_handler_invocation_end ON job_history(invocation_id)
 WHERE event_code IN ('HANDLER_COMPLETED','HANDLER_FAILED');
CREATE INDEX IF NOT EXISTS idx_job_history_job ON job_history(job_id,history_id);
CREATE INDEX IF NOT EXISTS idx_event_queue ON incoming_events(state,next_run_at_ms);
CREATE INDEX IF NOT EXISTS idx_event_lease ON incoming_events(state,lease_expires_at_ms);
CREATE INDEX IF NOT EXISTS idx_history_event ON event_history(event_id,history_id);
CREATE INDEX IF NOT EXISTS idx_anime_tvdb ON identified_anime(tvdb_series_id);
CREATE INDEX IF NOT EXISTS idx_episodes_anime ON identified_episodes(anidb_id);
CREATE INDEX IF NOT EXISTS idx_links_episode ON result_episode_links(anidb_episode_id);
CREATE TABLE IF NOT EXISTS provider_limits (
 provider TEXT PRIMARY KEY CHECK(provider IN ('anidb','anidb_titles','anime_lists','tvdb')),
 next_allowed_at_ms INTEGER NOT NULL CHECK(next_allowed_at_ms >= 0),
 failures INTEGER NOT NULL DEFAULT 0 CHECK(failures BETWEEN 0 AND 16),
 reservation_token TEXT NOT NULL CHECK(length(reservation_token)=32)
);
CREATE TABLE IF NOT EXISTS provider_public_cache (
 provider TEXT NOT NULL CHECK(provider IN ('anidb','anidb_titles','anime_lists')),
 cache_key TEXT NOT NULL CHECK(length(cache_key) BETWEEN 1 AND 64),
 fetched_at_ms INTEGER NOT NULL CHECK(fetched_at_ms >= 0),
 expires_at_ms INTEGER NOT NULL CHECK(expires_at_ms > fetched_at_ms),
 payload BLOB NOT NULL CHECK(typeof(payload)='blob' AND length(payload) BETWEEN 1 AND 67108864),
 PRIMARY KEY(provider,cache_key)
);
CREATE INDEX IF NOT EXISTS idx_provider_cache_expiry ON provider_public_cache(expires_at_ms);

CREATE TABLE IF NOT EXISTS release_verifications (
 verification_id INTEGER PRIMARY KEY,
 job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 identity_result_id INTEGER NOT NULL,
 anidb_id INTEGER NOT NULL,
 release_sha256 TEXT NOT NULL CHECK(length(release_sha256)=64 AND release_sha256 NOT GLOB '*[^a-f0-9]*'),
 verification_scope TEXT NOT NULL CHECK(verification_scope='DECLARED_SINGLE_EPISODE'),
 anidb_episode_number INTEGER NOT NULL CHECK(anidb_episode_number>0),
 anidb_episode_id INTEGER NOT NULL,
 tvdb_series_id INTEGER NOT NULL CHECK(tvdb_series_id>0),
 tvdb_season INTEGER NOT NULL CHECK(tvdb_season>=0),
 tvdb_episode INTEGER NOT NULL CHECK(tvdb_episode>0),
 tvdb_episode_id INTEGER NOT NULL CHECK(tvdb_episode_id>0),
 tvdb_order TEXT NOT NULL DEFAULT 'official' CHECK(tvdb_order='official'),
 verified_at_ms INTEGER NOT NULL CHECK(verified_at_ms>=0),
 FOREIGN KEY(identity_result_id,anidb_id) REFERENCES identity_results(result_id,anidb_id),
 FOREIGN KEY(anidb_episode_id,anidb_id) REFERENCES identified_episodes(anidb_episode_id,anidb_id)
);
CREATE INDEX IF NOT EXISTS idx_release_identity ON release_verifications(identity_result_id);

CREATE TABLE IF NOT EXISTS trial_plans (
 plan_id INTEGER PRIMARY KEY,
 anidb_id INTEGER NOT NULL REFERENCES identified_anime(anidb_id),
 tvdb_series_id INTEGER NOT NULL CHECK(tvdb_series_id>0),
 tvdb_season INTEGER NOT NULL CHECK(tvdb_season>=0),
 tvdb_order TEXT NOT NULL DEFAULT 'official' CHECK(tvdb_order='official'),
 anchor_verification_id INTEGER NOT NULL REFERENCES release_verifications(verification_id),
 anchor_episode INTEGER NOT NULL CHECK(anchor_episode>0),
 backfill_count INTEGER NOT NULL CHECK(backfill_count BETWEEN 0 AND 1000),
 following_count INTEGER NOT NULL CHECK(following_count BETWEEN 0 AND 1000),
 configuration_revision INTEGER NOT NULL CHECK(configuration_revision>0),
 created_at_ms INTEGER NOT NULL CHECK(created_at_ms>=0),
 UNIQUE(anidb_id,tvdb_series_id,tvdb_season,tvdb_order),
 CHECK(backfill_count>0 OR following_count>0),
 CHECK(following_count=0 OR anchor_episode<=9223372036854775807-following_count+1)
);
CREATE TABLE IF NOT EXISTS trial_evaluations (
 evaluation_id INTEGER PRIMARY KEY,
 job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 verification_id INTEGER NOT NULL REFERENCES release_verifications(verification_id),
 plan_id INTEGER REFERENCES trial_plans(plan_id),
 selected INTEGER NOT NULL CHECK(selected IN (0,1)),
 reason_code TEXT NOT NULL CHECK(reason_code IN ('TRIAL_SELECTED','TRIAL_OUTSIDE_WINDOW','TRIAL_DISABLED')),
 evaluated_at_ms INTEGER NOT NULL CHECK(evaluated_at_ms>=0),
 CHECK((plan_id IS NULL AND selected=0 AND reason_code='TRIAL_DISABLED') OR
       (plan_id IS NOT NULL AND ((selected=1 AND reason_code='TRIAL_SELECTED') OR
                                (selected=0 AND reason_code='TRIAL_OUTSIDE_WINDOW'))))
);
CREATE INDEX IF NOT EXISTS idx_trial_evaluations_plan ON trial_evaluations(plan_id);

CREATE TABLE IF NOT EXISTS episode_reservations (
 reservation_id INTEGER PRIMARY KEY,
 owner_job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 evaluation_job_id INTEGER NOT NULL REFERENCES jobs(job_id),
 verification_id INTEGER NOT NULL REFERENCES release_verifications(verification_id),
 plan_id INTEGER NOT NULL REFERENCES trial_plans(plan_id),
 anidb_id INTEGER NOT NULL REFERENCES identified_anime(anidb_id),
 anidb_episode_id INTEGER NOT NULL UNIQUE REFERENCES identified_episodes(anidb_episode_id),
 tvdb_series_id INTEGER NOT NULL CHECK(tvdb_series_id>0),
 tvdb_season INTEGER NOT NULL CHECK(tvdb_season>=0),
 tvdb_episode INTEGER NOT NULL CHECK(tvdb_episode>0),
 tvdb_episode_id INTEGER NOT NULL UNIQUE CHECK(tvdb_episode_id>0),
 tvdb_order TEXT NOT NULL DEFAULT 'official' CHECK(tvdb_order='official'),
 reserved_at_ms INTEGER NOT NULL CHECK(reserved_at_ms>=0),
 UNIQUE(tvdb_series_id,tvdb_season,tvdb_episode,tvdb_order)
);

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
        from src.nextgen.storage.migrations import _open, LATEST_VERSION, MigrationError, MigrationUnsupported
        try:
            db = _open(gate.database, readonly=False)
        except (OSError, sqlite3.Error):
            raise MigrationError() from None
        try:
            try:
                if db.execute("PRAGMA user_version").fetchone()[0] != LATEST_VERSION:
                    raise MigrationUnsupported()
                db.execute("PRAGMA busy_timeout=5000")
                db.execute("PRAGMA journal_mode=WAL")
            except sqlite3.Error:
                raise MigrationError() from None
            yield db
        finally:
            db.close()


def initialize(db):
    """Initialize a *new* NextGen database at schema v12; never implicitly upgrade.

    Existing v1/v2/v3/v4/v5/v6/v7/v8/v9/v10/v11 databases require explicit versioned SQL migrations
    before accessing v12 storage.
    """
    version = db.execute("PRAGMA user_version").fetchone()[0]
    if version == 12:
        return
    if version != 0:
        raise ValueError("existing NextGen database requires versioned SQL upgrade")
    present = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' LIMIT 1").fetchone()
    if present:
        raise ValueError("database has tables but no schema version; refuse implicit upgrade")
    if db.in_transaction:
        raise ValueError("initialization requires no active transaction")
    try:
        db.executescript("BEGIN IMMEDIATE;\n" + SCHEMA + "\nPRAGMA user_version=12;\nCOMMIT;")
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

class IdentityConflict(ValueError):
    reason_code = "IDENTITY_CONFLICT"

    def __init__(self):
        super().__init__("Conflicting anime information needs review.")


class IdentityNotReady(ValueError):
    reason_code = "IDENTITY_INCOMPLETE"

    def __init__(self):
        super().__init__("Anime identification is incomplete.")


def persist_identity(db, event_id, candidate, validated_at_ms=None):
    """Return result ID/audit inside caller transaction; never commit or log.

    Worker adapters must hold/fence their job lease. Existing incoming-event
    leases are deliberately not bypassed by this job-based persistence path.
    """
    if not db.in_transaction:
        raise ValueError("identity persistence requires an active transaction")
    from src.nextgen.schema.anime_series import AnimeSeries
    validated = AnimeSeries.from_dict(candidate)
    payload = validated.to_dict()
    anime = payload["anime"]
    aid = anime["anidb_id"]
    now = integer(int(time.time() * 1000) if validated_at_ms is None else validated_at_ms)
    integer(event_id, positive=True)
    event = db.execute("SELECT state,lease_token,lease_expires_at_ms FROM incoming_events WHERE event_id=?", (event_id,)).fetchone()
    if event is None:
        raise IdentityNotReady()
    existing_result = db.execute("SELECT result_id,series_json FROM identity_results WHERE event_id=? AND anidb_id=?", (event_id,aid)).fetchone()
    if existing_result is not None:
        if json.loads(existing_result[1]) != payload:
            raise IdentityConflict()
        return existing_result[0], None
    if event[0] not in ("PENDING","RUNNING","RETRY_WAIT"):
        raise IdentityNotReady()
    if event[0] == "RUNNING":
        raise IdentityNotReady()
    existing = db.execute(
        "SELECT tvdb_series_id,title FROM identified_anime WHERE anidb_id=?",
        (aid,)).fetchone()
    if existing and existing[0] != anime["tvdb_series_id"]:
        raise IdentityConflict()
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
            raise IdentityConflict()
        db.execute(
            "INSERT OR IGNORE INTO identified_episodes VALUES(?,?)",(eid,aid))
        db.execute(
            "INSERT INTO result_episode_links VALUES(?,?,?)",(rid,aid,eid))
    db.execute("UPDATE incoming_events SET state='IDENTIFIED', next_run_at_ms=NULL, lease_token=NULL, lease_expires_at_ms=NULL, last_reason_code=NULL WHERE event_id=?", (event_id,))
    audit = append_event_history(db, event_id=event_id, event_code="SERIES_IDENTIFIED",
                                 component="identity", occurred_at_ms=now)
    return rid, audit


def save_identity(db, event_id, candidate, validated_at_ms=None):
    """Store validated AnimeSeries v2; zero episodes are allowed."""
    with transaction(db):
        rid, audit = persist_identity(db,event_id,candidate,validated_at_ms)
    if audit is not None:
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
    if len(raw.encode("utf-8")) > 65536:
        raise ValueError("job payload exceeds the storage bound")
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


def enqueue_job_with_receipt(db, **kwargs):
    """Worker-owned handoff: return ID and audit receipt; no commit or logging."""
    return _enqueue_job(db, **kwargs)


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
