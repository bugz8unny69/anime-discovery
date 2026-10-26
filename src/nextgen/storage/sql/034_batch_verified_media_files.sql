-- v33 -> v34: append-only per-episode media proof, no staging permissions.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v34_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v34_guard SELECT user_version=33 FROM pragma_user_version;
CREATE TABLE batch_verified_media_files (
 plan_id INTEGER NOT NULL REFERENCES batch_torrent_unlocks(plan_id),
 file_index INTEGER NOT NULL,
 tvdb_episode INTEGER NOT NULL CHECK(tvdb_episode>0),
 evidence_json TEXT NOT NULL CHECK(json_valid(evidence_json) AND length(CAST(evidence_json AS BLOB))<=65536),
 verified_at_ms INTEGER NOT NULL CHECK(verified_at_ms>=0),
 PRIMARY KEY(plan_id,file_index),
 UNIQUE(plan_id,tvdb_episode),
 FOREIGN KEY(plan_id,file_index) REFERENCES batch_trial_files(plan_id,file_index)
);
INSERT OR ROLLBACK INTO nextgen_v34_guard SELECT count(*)=0 FROM pragma_foreign_key_check;
DROP TABLE nextgen_v34_guard;
PRAGMA user_version=34;
COMMIT;
