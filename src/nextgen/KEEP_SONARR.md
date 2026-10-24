# Keep through Sonarr

Keep now submits a background Sonarr v4 import for the single staged episode
selected by the management request. It reuses the existing staged path and both
provider identities. Sonarr matching uses the verified TVDB series, season,
episode and available episode ID. AniDB IDs remain available for optional Shoko;
there is no Shoko dependency or second staging/NFO implementation.

Configure the Sonarr address and private API key in Settings, plus the local
permanent Keep folder. A quality profile ID is required when adding a new series.
Optional staging/library roots describe the same folders as Sonarr sees them in
a container or another service. Blank uses the recorded staging root/local Keep
root. Both processes must actually have the corresponding storage mounted.

The job finds the exact TVDB series, or looks it up and adds it with the configured
root and profile. New series are monitored, without triggering a missing-episode
or cutoff search. Existing series roots/profiles/monitoring are not rewritten.
An existing series outside the configured permanent root needs review.

The job scans the staged parent folder, selects only the exact approved file,
and reprocesses that candidate with explicit Sonarr series/episode IDs. It uses
Sonarr's returned quality/languages and requires no import rejection. The actual
ManualImport command contains only that file and uses copy mode. Existing episode
files are not overwritten automatically. Series packs and other folder files
cannot silently join this import.

Keep records series-add/import intent before each external write. Lost replies
are reconciled by TVDB identity or a matching saved command; they never authorize
an automatic repeat POST. A command that failed, was purged, or cannot be matched
may require operator attention; explicitly resubmitting Keep resumes the same job
and journal. It does not erase an uncertain send or grant a second send right.
Before any external intent, a PLANNED job can take corrected settings on explicit
retry. After external authorization, client/root/options stay bound to the saved
plan. Credentials are read afresh. A per-job lock drains stale attempts before
recovered work proceeds, and queue leases fence mutations and completion.

The job waits without holding a worker slot while Sonarr works. Kept is recorded
after the command completes, Sonarr binds the expected episode to its file, and
that regular readable file exists under the configured local permanent folder
with the expected size. There is no destination checksum or byte-for-byte
comparison. A returned command ID alone is not a successful import.

Staging files and NFOs remain after Keep. Post-Keep source cleanup and optional
Shoko registration remain separate work. Configured Jellyfin refresh is now an
independent follow-up; see JELLYFIN_REFRESH.md. This job does not
delete staged videos, torrent data or permanent media. It imports the selected
episode, not every staged episode for the anime. Subsequent selected episodes
retain their own explicit acquisition/Keep scope.

The dashboard enables Keep for eligible staged work and uses existing job
receipts, polling and disabled-button explanations. It displays the catalog
message "This episode has been kept." only when a durable Keep result exists.
Held/review work can explicitly resume the same job after the cause is addressed.
Successful imports are not submitted again. Old KEEP_NOT_READY history stays
readable; these stopped jobs resume only through an explicit Keep request.

Configuration v8 explicitly adds Sonarr settings; existing v0–v7 shapes remain
versioned. Secrets v4 adds the API key while v1–v3 files remain readable and retain
their format until a Sonarr credential write. API reads expose presence only.
The existing management session/Bearer, CSRF and separate webhook authentication
contracts remain unchanged. SQLite v22 adds keep_imports alongside immutable
001–021 migrations. Startup performs no implicit configuration/SQL upgrade.

Offline tests cover staged import, new/existing series, lost add/import replies,
duplicate/resumed actions, changed files, wrong destinations, pinned settings,
credential isolation and migration preservation/rollback. They remain unrun,
as does CI. Source/syntax/DDL checks do not verify Sonarr/browser runtime behavior.
No live service, import, media deletion, production migration or deployment ran.

API payloads were checked against Sonarr's official source: ManualImportController,
ManualImportResource, ManualImportFile and ManualImportCommand under
https://github.com/Sonarr/Sonarr/tree/develop/src . Sonarr's API v3 routes are
used for Sonarr v4; unreviewed server major versions stop for review.
