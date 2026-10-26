-- v35 -> v36: one-shot stopped E01 handoff before audio unlock.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v36_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v36_guard SELECT user_version=35 FROM pragma_user_version;
CREATE TABLE batch_probe_stops (
 plan_id INTEGER PRIMARY KEY REFERENCES batch_torrent_transfers(plan_id),
 stop_job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 first_attempt INTEGER NOT NULL CHECK(first_attempt>0),
 fingerprint TEXT NOT NULL CHECK(length(fingerprint)=64 AND fingerprint NOT GLOB '*[^a-f0-9]*'),
 phase TEXT NOT NULL CHECK(phase IN ('STOP_UNCERTAIN','STOPPED','REVIEW')),
 reason_code TEXT NOT NULL CHECK(
   (phase='STOP_UNCERTAIN' AND reason_code='TORRENT_STOP_UNCERTAIN') OR
   (phase='STOPPED' AND reason_code='TORRENT_STOPPED_CONFIRMED') OR
   (phase='REVIEW' AND reason_code='TORRENT_TRANSFER_CONFLICT')),
 created_at_ms INTEGER NOT NULL CHECK(created_at_ms>=0),
 updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms>=created_at_ms)
);
INSERT OR ROLLBACK INTO nextgen_v36_guard SELECT count(*)=0 FROM pragma_foreign_key_check;
DROP TABLE nextgen_v36_guard;
PRAGMA user_version=36;
COMMIT;
