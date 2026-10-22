-- NextGen SQLite schema version 2: incremental change from version 1.
-- Apply once to a database at PRAGMA user_version=1.
-- The future migration runner must verify version before applying.
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

PRAGMA user_version=2;
