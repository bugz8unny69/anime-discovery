-- v37 -> v38: durable stage cleanup after complete batch Sonarr Keep.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v38_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v38_guard SELECT user_version=37 FROM pragma_user_version;
CREATE TABLE batch_stage_cleanups (
 job_id INTEGER PRIMARY KEY REFERENCES jobs(job_id),
 keep_job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 plan_id INTEGER NOT NULL REFERENCES batch_trial_plans(plan_id),
 phase TEXT NOT NULL CHECK(phase IN ('PLANNED','COMPLETE')),
 created_at_ms INTEGER NOT NULL CHECK(created_at_ms>=0),
 updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms>=created_at_ms)
);
INSERT OR ROLLBACK INTO nextgen_v38_guard SELECT count(*)=0 FROM pragma_foreign_key_check;
DROP TABLE nextgen_v38_guard;
PRAGMA user_version=38;
COMMIT;
