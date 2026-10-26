-- v34 -> v35: durable per-file copy-only staging intents and receipts.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v35_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v35_guard SELECT user_version=34 FROM pragma_user_version;
CREATE TABLE batch_staging_publications (
 plan_id INTEGER NOT NULL,
 file_index INTEGER NOT NULL,
 tvdb_episode INTEGER NOT NULL CHECK(tvdb_episode>0),
 job_id INTEGER NOT NULL REFERENCES jobs(job_id),
 manifest_json TEXT NOT NULL CHECK(json_valid(manifest_json) AND length(CAST(manifest_json AS BLOB))<=65536),
 state TEXT NOT NULL CHECK(state IN ('PLANNED','PUBLISHED')),
 receipts_json TEXT CHECK(receipts_json IS NULL OR (json_valid(receipts_json) AND length(CAST(receipts_json AS BLOB))<=65536)),
 created_at_ms INTEGER NOT NULL CHECK(created_at_ms>=0),
 published_at_ms INTEGER,
 PRIMARY KEY(plan_id,file_index),
 UNIQUE(plan_id,tvdb_episode),
 FOREIGN KEY(plan_id,file_index) REFERENCES batch_verified_media_files(plan_id,file_index),
 CHECK((state='PLANNED' AND receipts_json IS NULL AND published_at_ms IS NULL) OR
       (state='PUBLISHED' AND receipts_json IS NOT NULL AND published_at_ms>=created_at_ms))
);
CREATE INDEX idx_batch_staging_job ON batch_staging_publications(job_id,state);
INSERT OR ROLLBACK INTO nextgen_v35_guard SELECT count(*)=0 FROM pragma_foreign_key_check;
DROP TABLE nextgen_v35_guard;
PRAGMA user_version=35;
COMMIT;
