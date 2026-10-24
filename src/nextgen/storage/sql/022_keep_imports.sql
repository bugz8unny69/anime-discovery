-- v21 -> v22: atomic approved Keep snapshots; no implicit Sonarr calls.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v22_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v22_guard SELECT user_version=21 FROM pragma_user_version;
CREATE TABLE IF NOT EXISTS keep_imports (
 operation_id INTEGER PRIMARY KEY REFERENCES job_operations(operation_id),
 keep_job_id INTEGER NOT NULL UNIQUE REFERENCES jobs(job_id),
 staging_plan_id INTEGER NOT NULL UNIQUE REFERENCES staging_publications(plan_id),
 approval_json TEXT NOT NULL CHECK(json_valid(approval_json) AND length(CAST(approval_json AS BLOB)) BETWEEN 1 AND 131072),
 approval_sha256 TEXT NOT NULL CHECK(length(approval_sha256)=64 AND approval_sha256 NOT GLOB '*[^a-f0-9]*'),
 phase TEXT NOT NULL CHECK(phase IN ('APPROVED','SERIES_INTENT','SERIES_READY','IMPORT_INTENT','COMMAND_ACCEPTED','VERIFIED','REVIEW')),
 sonarr_series_id INTEGER CHECK(sonarr_series_id IS NULL OR sonarr_series_id>0),
 sonarr_command_id INTEGER CHECK(sonarr_command_id IS NULL OR sonarr_command_id>0),
 library_evidence_json TEXT CHECK(library_evidence_json IS NULL OR (json_valid(library_evidence_json) AND length(CAST(library_evidence_json AS BLOB)) BETWEEN 1 AND 65536)),
 approved_at_ms INTEGER NOT NULL CHECK(approved_at_ms>=0),
 updated_at_ms INTEGER NOT NULL CHECK(updated_at_ms>=approved_at_ms),
 CHECK(phase NOT IN ('IMPORT_INTENT','COMMAND_ACCEPTED','VERIFIED') OR sonarr_series_id IS NOT NULL),
 CHECK(phase NOT IN ('COMMAND_ACCEPTED','VERIFIED') OR sonarr_command_id IS NOT NULL),
 CHECK(phase<>'VERIFIED' OR library_evidence_json IS NOT NULL)
);
DROP TABLE nextgen_v22_guard;
PRAGMA user_version=22;
COMMIT;
