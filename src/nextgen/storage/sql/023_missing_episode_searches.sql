-- v22 -> v23: record provider candidates without admitting torrents into Intake.
BEGIN IMMEDIATE;
CREATE TEMP TABLE nextgen_v23_guard(ok INTEGER CHECK(ok=1));
INSERT OR ROLLBACK INTO nextgen_v23_guard SELECT user_version=22 FROM pragma_user_version;
CREATE TABLE IF NOT EXISTS missing_episode_searches (
 plan_id INTEGER NOT NULL REFERENCES trial_plans(plan_id),
 tvdb_episode INTEGER NOT NULL CHECK(tvdb_episode>0),
 search_job_id INTEGER NOT NULL REFERENCES jobs(job_id),
 status TEXT NOT NULL CHECK(status IN ('FOUND','NO_MATCH')),
 candidate_count INTEGER NOT NULL CHECK(candidate_count BETWEEN 0 AND 25),
 searched_at_ms INTEGER NOT NULL CHECK(searched_at_ms>=0),
 PRIMARY KEY(plan_id,tvdb_episode)
);
CREATE TABLE IF NOT EXISTS missing_episode_candidates (
 plan_id INTEGER NOT NULL,
 tvdb_episode INTEGER NOT NULL,
 info_hash TEXT NOT NULL CHECK(length(info_hash)=40 AND info_hash NOT GLOB '*[^a-f0-9]*'),
 release_name TEXT NOT NULL CHECK(length(release_name) BETWEEN 1 AND 1024),
 discovered_at_ms INTEGER NOT NULL CHECK(discovered_at_ms>=0),
 PRIMARY KEY(plan_id,tvdb_episode,info_hash),
 FOREIGN KEY(plan_id,tvdb_episode) REFERENCES missing_episode_searches(plan_id,tvdb_episode)
);
DROP TABLE nextgen_v23_guard;
PRAGMA user_version=23;
COMMIT;
