# One-time settings fix

Stop the old service, then run:

```sh
sudo python3 fixes/migrate_legacy_settings.py
```

It backs up the original settings and credentials under a private `.settings-backup-*` directory inside `/etc/anime-discovery`, then converts those two files in place. Compatible values and file ownership are retained. A repeat run validates the converted configuration and does nothing. Interrupted writes are recovered from the backup on the next run.

No database is read or changed. The new application database location is recorded automatically. The old administrator password remains in the backup; use ADM to set the new password. Unsupported settings are reported by name and remain in the backup.

Run the installer normally afterward. No manual directory moves are needed. `--config-dir` is available only for installations using another location.
