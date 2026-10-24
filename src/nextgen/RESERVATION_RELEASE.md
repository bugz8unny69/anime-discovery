# Releasing canceled acquisition reservations

SQLite v23 adds ACTIVE/RELEASED reservation state, ending time/job provenance and
partial unique indexes for active AniDB/TVDB episode slots. Acquisition plans
retain their IDs, manifests and markers; PREPARED/RELEASED state and a partial
unique infohash index allow the same torrent to be prepared again after cleanup.
Released rows stop contributing to the plan's active size budget. The original
budget limits and frozen episode-selection plan are retained.

A slot is released only inside the transaction recording CANCELED/COMPLETE,
while the existing exclusive operation lock proves workers have drained. Known
owned torrent/file cleanup must already be complete; shared consumers, uncertain
client outcomes, running work and published staging prevent release. The new
release event has a catalog reason and preserves prior job/reservation history.
No old canceled job is restarted: a later verified delivery creates new jobs,
reservation, preparation, marker and submission intent. Released source records
cannot authorize another acquisition or submission.

Kept/staged operations remain STAGED and retain active reservation/duplicate
protection. Reject decisions remain independent. This change does not remove
permanent media, restore rejected anime or search for missing episodes.

The API's reservation-only cancellation path can release locally after acquiring
the same drain lock; if a separate consumer prevents release, it records the
cancellation and queues the existing cleanup control job for review. Existing
completed cancellations with retained active slots expose Cleanup again. An
explicit cleanup rechecks the old journal and can retire the retained slot,
including resuming an old DONE cleanup job. Migration does not automatically
release historical slots or contact the download client.

Migration 023 rebuilds the two tables under drained maintenance, preserving row
IDs, data and foreign-key targets. The migration runner validates structure and
foreign keys before commit and restores FK enforcement after failure. SQL 001–022
are unchanged. Existing v22 databases require the explicit upgrade; there is no
runtime automatic upgrade. Configuration stays v9 and secrets v5.

Offline cases for cancel/reacquire of the same episode/hash, active budgets,
history preservation, source fencing, staged/kept protection, pending cleanup,
older completed cancellations, migration preservation/equality and rollback are
authored but unrun. Python/source checks do not establish migration correctness.
No SQL, tests, CI, live services, media deletion or deployment was run.

Remaining work includes download/torrent cleanup after Keep/Reject, optional
Shoko integration, service lifecycle/setup and end-to-end lab validation. Existing
cancellation download cleanup is reused, rather than being reimplemented here.
