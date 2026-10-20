# Anime-Trial staging ownership and group access

Anime Discovery's trial staging originally copied into a `tempfile.mkstemp`
file, which defaults to mode `0600`; hard-linking that inode into the
final `Season 01/S01E01.mkv` retained the private mode and prevented
Jellyfin from accessing the file through its shared media group.

Configure via **Settings → Staged media permissions**:

- **Staged file owner (optional)**: blank (recommended) retains the
  `anime-discovery` service account. A username or numeric UID may be
  supplied when the service is allowed to assign it. The service never
  elevates permissions or invokes sudo.
- **Staged file group (optional)**: blank retains the existing service
  group. A group name such as `media` or numeric GID such as `1002`
  assigns new MKVs and NFOs to the desired sharing group. The daemon
  must have that group in its supplementary list, or the storage must
  permit the change.

The new publisher ensures mode `0640` on staged files and NFOs.
Named series and season folders are group-traversable when a group
is configured. Mode and owner assignment happens *before* the file is
published from the temporary staging inode. Permission errors abort
staging instead of falsely marking acquisition `DONE`.

The root trial mount and its ACLs must still grant appropriate traversal;
NFSv4 server ACLs can override local POSIX expectations. A successful
`chmod` and `chgrp` are verified by a readback on the client.

## Current media is not retroactively modified

Setting a new staged owner/group only applies to future staging. For
previously completed Solo Leveling episodes, inspect the metadata first:

```sh
stat -c '%a %u:%g %n' '/mnt/media/Anime-Trial/Solo Leveling/Season 01/'*.mkv
```

If the local NAS access model permits it, an administrator can separately
repair existing copies by changing their group to `media` and mode to
`0640`; confirm existing NFO permissions too. Do not rerun acquisition
or remove originals solely to fix permissions. Verify that Jellyfin itself
can read the file through its mounted NFS path.
