-- v38 -> v39: one-shot owned full-torrent and exact-file cleanup after batch decisions.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v39_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v39_guard SELECT user_version=38 FROM pragma_user_version;
CREATE TABLE batch_download_cleanups (
 plan_id INTEGER PRIMARY KEY REFERENCES batch_torrent_submissions(plan_id),
 cleanup_job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 decision_job_id INTEGER NOT NULL REFERENCES jobs(job_id),
 target_operation_id INTEGER NOT NULL REFERENCES job_operations(operation_id),
 fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^a-f0-9]*'),
 phase TEXT NOT NULL CHECK(phase IN ('PREPARED','STOP_UNCERTAIN','REMOVE_UNCERTAIN','FILES','COMPLETE','REVIEW')),
 files_json TEXT NOT NULL CHECK(json_valid(files_json) AND length(CAST(files_json AS BLOB))<=1048576),
 created_at_ms INTEGER NOT NULL CHECK(created_at_ms>=0),
 updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms>=created_at_ms)
);
CREATE UNIQUE INDEX idx_batch_cleanup_decision ON batch_download_cleanups(decision_job_id);
INSERT OR ROLLBACK INTO nextgen_v39_guard SELECT count(*)=0 FROM pragma_foreign_key_check;
DROP TABLE nextgen_v39_guard;
PRAGMA user_version=39;
COMMIT;
