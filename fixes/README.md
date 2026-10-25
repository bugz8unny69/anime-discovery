# One-time settings conversion

This script copies compatible legacy settings and provider credentials into a separate private configuration directory. It leaves the originals unchanged and never imports the operational database or administrator password. Set the administrator password through ADM after installation.

Preview (does not change files):

```sh
python3 fixes/migrate_legacy_settings.py --legacy-config-dir /etc/anime-discovery --output-dir /etc/anime-discovery-converted --database /var/lib/anime-discovery/anime-discovery.sqlite
```

Review the mapped and unsupported field names, then repeat with `--apply`. Use `--uid SERVICE_UID --gid SERVICE_GID` for the anime-discovery service account, so the service can read and update the private files. If the account does not yet exist, create the dedicated system account first. Output files have mode 0600 and the directory has mode 0700.

Keep the original directory as a backup. Once conversion succeeds and the old service is stopped, move the original directory aside and move the converted directory to `/etc/anime-discovery`, then run the installer. Do not run the converter with the same source and destination. The converter never moves directories or stops services itself.

Use `--settings-file` with a native settings object to explicitly override incompatible values. A repeat with identical source inputs preserves subsequent edits to the converted configuration. Changed inputs require a new output directory.
