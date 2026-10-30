# Download cleanup after staging, Keep or Reject

**Since 2026-10-29:** staging moves the verified video out of the torrent's
folder, so the torrent has nothing left to seed. Each completed
STAGE_TRIAL_MEDIA job now queues one CLEANUP_DECIDED_DOWNLOAD job
(`{"staging_job_id": N}`), due one minute later in its own operation. It uses
the same owned-cleanup journal described below: stop, remove the exact owned
torrent from qBittorrent, then remove leftover manifest files. The staging and
permanent folders are protected. The later Keep/Reject cleanup finds the
journal COMPLETE and does nothing more. Batch staging is unchanged.


New successful Reject completions enqueue one CLEANUP_DECIDED_DOWNLOAD job in
an independent control operation. Keep queues it only when the post-Keep selected
staging cleanup job completes successfully. Enqueue and predecessor completion
share the worker's completion transaction. Existing completed decisions are not
automatically backfilled. No database/configuration/secrets upgrade is added:
SQLite v23, configuration v9 and secrets v5 remain current.

The worker requires the original completed management decision, the published
staging plan, the correct predecessor and event, and the exact acquisition plan.
Keep must have a COMPLETE Sonarr journal and completed selected staging cleanup.
Reject must have its persisted decision and completed selected cleanup. The
historical cleanup reader does not relax the acquisition reader's rejected-anime
fence: rejected work can be cleaned but can never be submitted again by this job.

The target acquisition operation remains STAGED. Exclusive OperationGate drain
protection serializes cleanup and recovered attempts. Every target member must
be DONE or CANCELED; consumers in another explicit operation prevent cleanup.
The recorded OWNED_STOPPED submission intent pins endpoint, marker, manifest,
category and exact save path; current credentials are used. The old intent state
is an ownership receipt, not proof that the client is still stopped.

Cancellation and decision cleanup share OwnedCleanup and the existing
cancellation_cleanup table (its historical name remains internal). The same
PREPARED -> STOP_UNCERTAIN -> REMOVE_UNCERTAIN -> FILES -> COMPLETE journal
records intent before external requests. Stop is skipped when already stopped.
The exact owned torrent is removed with deleteFiles=false; only after confirmed
absence does manifest-based local file removal run. A lost response reconciles
without another stop/remove permit. A request that remains uncertain does not
get automatically reissued, including after explicit retry.

Before removal, the downloaded root must match the device/inode recorded during
media verification. Current and recorded staging/permanent roots are protected.
Unknown files, symlinks, hardlinks, replaced roots/files and changed ownership
prevent deletion. Remaining declared partial payloads are captured with their
file signatures, then unlinked only if those signatures still match. Directories
are retained. No recursive deletion, destination hashing, media reimport or
reservation release occurs. Kept episode protection and rejected-anime decisions
remain intact.

Management receipts expose download_cleanup separately from decision completion
and post_keep_cleanup. The dashboard shows progress and readable reasons. A
stopped review/blocked cleanup exposes Retry download cleanup through the same
Keep/Reject action; it resumes the exact follow-up job without repeating the
decision, staging cleanup or Sonarr import. A waiting or running job stays disabled.

Offline cases cover Keep and Reject handoffs, partial remaining payloads,
permanent/shared metadata preservation, kept reservations, shared consumers,
changed ownership/root/files, lost stop/remove replies, no replay after an
uncertain removal, and explicit retry without reimport. Tests remain unrun.
Python AST, JavaScript syntax, catalog/source and whitespace checks are not
runtime validation. No SQL, tests, CI, live client calls, media operations,
service changes, merge or deployment were performed.

Remaining implementation: optional Shoko integration and service lifecycle/setup.
The architecture deliberately has no automatic missing-episode search; intake
uses verified release deliveries and the configured episode window. Full lab
validation and explicit schema upgrade validation remain pending.
