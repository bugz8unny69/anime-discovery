# One-time settings fix

Stop the old service, then run:

```sh
sudo python3 fixes/migrate_legacy_settings.py
```

It backs up the original settings and credentials under a private `.settings-backup-*` directory inside `/etc/anime-discovery`, then converts those two files in place. Compatible values and file ownership are retained. A repeat run validates the converted configuration and does nothing. Interrupted writes are recovered from the backup on the next run.

No database is read or changed. The new application database location is recorded automatically. The old administrator password remains in the backup; use ADM to set the new password. Unsupported settings are reported by name and remain in the backup.

Run the installer normally afterward. No manual directory moves are needed. `--config-dir` is available only for installations using another location.


## One-time cleanup of obsolete Sonarr backfill results

Previous Sonarr discovery sometimes saved NOT_LISTED for episodes that had never
been searched using Prowlarr. The series Intake page cannot offer Retry for that
obsolete status. This separate one-time repair clears only unclaimed NOT_LISTED
*result rows*. Intake then reports those episodes as Not searched and offers
the existing Prowlarr Search action. It does not rewrite history, migrate the
schema, re-run discovery, or remove acquired/staged episodes.

After merging this fix into NextGen and running anime-discovery-install --upgrade,
first preview (read-only, services may be running):

```sh
sudo python3 /opt/anime-discovery/current/fixes/cleanup_legacy_not_listed.py
```


Review the eligible and protected counts. If the result is as expected, stop
both services, apply (which creates a private 0600 SQLite backup alongside the
database), and start the services again:

```sh
sudo systemctl stop anime-discovery-worker.service anime-discovery-api.service
sudo python3 /opt/anime-discovery/current/fixes/cleanup_legacy_not_listed.py --apply
sudo systemctl start anime-discovery-api.service anime-discovery-worker.service
```


Only rows without an active reservation or saved candidate/selection are
removed. Protected rows are reported and left unchanged. A second application
does nothing. The script requires the NextGen v48 database layout. If it
refuses, inspect the reported reason rather than forcing changes.
