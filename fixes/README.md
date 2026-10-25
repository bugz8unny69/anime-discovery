# One-time settings conversion

Run from your checkout:

```sh
sudo python3 fixes/migrate_legacy_settings.py
```

The script reads `/etc/anime-discovery`, asks for confirmation, and writes converted settings to `/etc/anime-discovery-converted`. Your original files stay unchanged. It uses the existing `anime-discovery` service account for ownership; that account must exist first.

No database is read or imported. The new database location is set automatically. The old administrator password is not imported; set the new password through ADM after installation.

After successful conversion, stop the old service, keep the original configuration directory as a backup, and put the converted directory at `/etc/anime-discovery` before running the installer.

Optional: `--preview` prints the summary without writing, and `--apply` writes without asking. Custom source/destination paths and overrides remain available in `--help`.
