# Reject staged media

Reject now uses the same authenticated versioned API, dashboard action receipt
and worker queue as Keep/Cancel. POST `/api/v1/jobs/<id>/reject` accepts an empty
JSON object. Browser requests require the existing session and CSRF token; webhook
credentials cannot authorize it. The dashboard explains and confirms its scope.

A selected staged acquisition supplies the exact verified AniDB anime ID and its
published staging manifest. Admission atomically records the Reject decision and
REJECT_MEDIA control job. Repeated clicks reuse that job. A conflicting existing
Keep request is not converted into Reject. Decisions use the AniDB anime ID, not
a shared TVDB series ID: sequel/cour entries with distinct AniDB IDs remain separate.

The rejected anime stops automatic Intake selection/reservation. Existing prepared
acquisition jobs also recheck the decision through their normal source-plan reads.
Incoming deliveries remain recorded and identified; future selection goes ON_HOLD
with ANIME_REJECTED instead of disappearing. This is not an automatic bulk cancel
of other in-flight operations. Already-staged episodes belonging to other
acquisitions are preserved; their Keep buttons reflect the rejected anime decision.

The Reject worker removes only the selected acquisition's recorded staged video
and episode NFO. It preserves shared tvshow.nfo, other episodes, unrelated files,
empty directories and permanent-library media. No extra video checksumming or
byte comparison is added. Missing selected files reconcile as already removed;
a changed file enters review. The decision remains effective while cleanup waits.
Retrying a Reject job after review resumes the existing cleanup rather than
creating another decision or targeting a wider scope.

SQLite v21 adds anime_review_decisions and extends management_actions to include
REJECT, preserving existing action rows. Existing databases upgrade explicitly;
configuration remains v7 and secrets v3. There is not yet a reconsider/unreject
UI or automatic release of existing episode reservations. Keep/Sonarr import,
viewer refresh and optional integrations remain separate work.

Offline cases cover queued admission, duplicate clicks, selected cleanup, shared
metadata preservation, changed/missing files, manual cleanup resumption, future
episode blocking and schema preservation/rollback. Tests and CI remain unrun.
No live viewer/client calls, file deletion, migration execution or deployment.
