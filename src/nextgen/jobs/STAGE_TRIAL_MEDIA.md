# Stage verified viewing media

The default worker advances VERIFY_MEDIA into STAGE_TRIAL_MEDIA in the same
worker-owned completion transaction. Its payload contains only the completed
verification job ID. A separate immutable staging_publications record binds
that verification, acquisition plan, source evidence, destination root identity,
configuration revision, generated filenames and minted temporary names before
any staging file is created. SQLite v20 requires an explicit maintenance upgrade;
configuration remains v7 and secrets v3. No historical DONE-job sweep is added.

## Layout and metadata

Use the existing staging-folder setting, storage.trial_root. It must already
exist, be accessible to the non-root worker and be separate from the download,
permanent and database paths. The actual source remains the pinned per-acquisition
download root. A changed setting controls new plans only: interrupted publication
continues at its recorded root, refusing replacement of that root inode.

The current deterministic layout is:

- `<safe title> [tvdbid-<series>] [anidbid-<anime>]/tvshow.nfo`
- `<series folder>/Season <NN>/<safe title> - S<NN>E<NN>.<mkv|mp4>`
- An episode NFO beside the video with the same basename.

Paths use a bounded title projection plus numeric provider identities; release
paths never choose destinations. NFO XML preserves the provider title as escaped
text, series/episode unique IDs and the verified TVDB season/episode placement.
Season zero remains season zero. Episode display titles currently use `Episode N`;
no unavailable episode name or artwork is invented. Different AniDB entries with
the same TVDB series use separate explicitly identified series folders.

New cross-filesystem files and NFO files are set to 0644; new directories request
0755 subject to the service umask. A same-filesystem move preserves the video's
existing ownership and permissions. Groups inherit normal filesystem policy for
new files. This initial version does not offer group/mode settings or chown/repair
existing paths. Operators must preconfigure root traversal/read access and a
service umask appropriate for the viewer. Configurable permissions and real
Jellyfin recognition checks remain operational follow-ups.

## Move and publication

**User decision, 2026-10-23: move the selected file into staging, without a
byte-for-byte copy verification.** The earlier viewing-copy proposal is superseded.
The existing media/audio verification stays before staging. The source checksum
is retained as provenance with `hash_checked=false` for the staged video; it is not recomputed or asserted as independently
verified destination content by the staging step.

Use component-by-component no-symlink directory opens. The selected source must
still match its recorded root, inode, size, mtime and ctime. On one filesystem,
record the exact source inode against a planned temporary destination, then rename
it without overwrite. No video bytes are copied or read back. This preserves its
inode and removes the source name as part of the move.

Across filesystems, stream into an exclusively created `.ad-<random>.partial` in
the actual destination directory, registering its inode before writing. Require
completed I/O, the expected size and unchanged source metadata. Do not hash or
compare the destination video. Flush the temporary, publish without overwrite,
and remove only the still-matching original source after all outputs are ready.
This is the normal copy-then-remove fallback required for a cross-filesystem move.

Record PUBLISH_UNCERTAIN before Linux renameat2(RENAME_NOREPLACE), recheck the
absolute directory and temporary inode, then rename and synchronize the directory.
Unsupported no-replace rename enters review; no overwriting fallback is used.
Recovery requires the original destination inode and expected size. Small generated
NFOs are compared with their planned XML; a shared tvshow.nfo can be reused only
with exact content. A short directory lock serializes shared metadata publication.

A dedicated job publication lock survives lease expiration until an old I/O thread
exits. Other attempts defer while it is held. Existing OperationGate admission
protects cancellation cleanup until staging attempts drain. Filesystem operations
and SQLite do not commit atomically; durable intent and inode reconciliation handle
an interrupted move. No extra byte-for-byte durability check is introduced.

## Recovery and cancellation

- A registered TEMP resumes the same recorded inode: finish a pending source rename, use its moved file, or resume an incomplete cross-filesystem write.
- PUBLISH_UNCERTAIN with the original temporary inode and expected size can
  finish the no-replace rename without copying again.
- PUBLISH_UNCERTAIN with an existing final file reconciles its exact original
  inode, size and directory identity; it never consumes a new source file.
- A creation crash before the temporary receipt leaves an unregistered file for
  review. Do not sweep it or adopt it merely because its random name matches.
- Unexpected existing files, changed roots, mismatched source/destination identity or size
  or missing published files stop for review and preserve what remains.
- Failure while publishing NFO files preserves a published video; a same-filesystem move may already have removed the source name. It does not mark the acquisition staged. Later retries reconcile the
  existing video instead of recopying it.
- Cancellation uses the existing registered-temporary cleanup contract. Published
  files are preserved; uncertain publication requires review. Empty directories
  are retained. No recursive directory cleanup is introduced.

After all three output files have their identity and expected size checked, worker completion checks the durable
plan, current verification and published artifact receipts, persists the final
manifest, marks the operation STAGED and sets the staging job DONE together.
Lease loss/cancellation prevents that database completion. STAGED closes Cancel;
Keep stays unavailable until permanent-library execution is implemented.

This version does not call Jellyfin, Shoko or Sonarr, trigger refresh, or implement
Keep/Reject. Automatic scan behavior and media-server naming recognition require
later integration validation. All authored offline filesystem/worker/migration
cases and CI remain unrun. No live source files, clients, viewers, migrations or
services were contacted during implementation.
