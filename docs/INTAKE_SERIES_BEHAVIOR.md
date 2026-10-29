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

## Missing episodes

Backfill remains Prowlarr-based. NO_RESULTS, NOT_AIRED, MAPPING_MISSING and
not-yet-searched episodes in the frozen window may be re-searched from Intake.
The original discovery handler targets exactly one episode and updates its
previous noncandidate result. Active reservations, already-selected releases
and active search jobs are not re-sent. Failed downloads keep using the ranked
candidate fallback after cleanup.

No new database schema, ranking engine or second acquisition/import pipeline.

## Limitations

- Existing library episodes predating NextGen are not detected.
- Series synopsis and artwork are not stored in the identity schema.
- Retry does not reset a CANDIDATES result after exhaustion; that remains
  separate from searching an episode that had no candidate.
- Series Keep is one user action with individual existing import jobs, not an
  atomic multi-file Sonarr import.
- No live homelab execution, deployment or GitHub Actions run.
