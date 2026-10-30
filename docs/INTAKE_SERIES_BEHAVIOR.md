# Series-first Intake and retrying missing backfill episodes

## Intake

Intake is grouped by identified AniDB anime, not webhook or worker job. Clicking
a series shows persisted identity details, staged episodes, and results from its
frozen backfill/continue episode windows. The AnimeSeries schema has no synopsis
or artwork field; the UI does not invent either. Jobs/history remain available.

## Keep

One Keep all staged action freezes the displayed operation IDs and submits the
existing idempotent single/batch Keep jobs. Existing Sonarr ManualImport,
verification, cleanup, and retry journals are reused, with partial submission
reported explicitly. New arrivals are never silently included.

Keep does not create or modify a series in Sonarr. A missing registered series
stops for review without removing staged files.

## Reject

Reject series is a single operator decision scoped to one verified AniDB ID.
The dialog records a required reason and an optional note, and the durable
decision immediately prevents future automatic Intake. Already active
reservations are canceled through the existing cancellation workflow and
their owned torrents go through the regular cancellation cleanup.

The queued series worker removes each staged acquisition's pinned video and
episode NFO using the existing receipt-based remover. Unrelated media,
shared series metadata, and anything in the permanent Keep library are never
deleted. For single-episode torrents it uses the existing post-stage download
cleanup; for season packs it uses the existing batch owned-torrent cleanup.
The series decision completes only once each resulting cleanup job completes.
Failures remain visible in Jobs/History and are not silently treated as success.

The decision reason and progress are visible in the series modal and the
rejection job's History. A user clicking Reject twice receives the same
decision rather than scheduling a second deletion. There is no automatic
unreject UI. The v50 database migration adds an optional reason field to
existing rejection decisions, leaving older decisions valid. Stop the API and
worker, run the normal explicit database preview/upgrade flow, and restart
with the new code; never start v50 services against an older database.

## Missing episodes

Backfill remains Prowlarr-based. NO_RESULTS, NOT_AIRED, MAPPING_MISSING and
not-yet-searched episodes in the frozen window may be re-searched from Intake.
The original discovery handler targets exactly one episode and updates its
previous noncandidate result. Active reservations, already-selected releases
and active search jobs are not re-sent. Failed downloads keep using the ranked
candidate fallback after cleanup.

No new ranking engine or second acquisition/import pipeline. No changes to
NOT_AIRED Retry Search; it stays manually available.

## Limitations

- Existing library episodes predating NextGen are not detected.
- Series synopsis and artwork are not stored in the identity schema.
- Retry does not reset a CANDIDATES result after exhaustion; that remains
  separate from searching an episode that had no candidate.
- Series Keep is one user action with individual existing import jobs, not an
  atomic multi-file Sonarr import.
- No live homelab execution, deployment or GitHub Actions run.
