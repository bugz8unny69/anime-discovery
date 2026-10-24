# NextGen installation and upgrades

Run the standalone `bin/anime-discovery-install` from a reviewed checkout. It uses Python's standard library, asks questions by default, and accepts switches for unattended operation. Python 3.11+, git, runuser, systemd and Python venv/pip are required. Use `--install-system-deps` to install dependencies with apt-get on Debian/Ubuntu; this is never implied by `--yes`.

Preview without making changes:

```sh
python3 bin/anime-discovery-install --plan
```

Install interactively:

```sh
sudo python3 bin/anime-discovery-install
```

Install unattended from a local reviewed Git checkout:

```sh
sudo python3 bin/anime-discovery-install --yes --source-dir /path/to/checkout --public-origin https://anime.example.com --settings-file /path/to/native-settings.json --start api --enable
```

`--source-dir` installs committed tracked files at HEAD, not working-tree edits. Otherwise the installer fetches the private repository's NextGen branch using root's existing Git access. `--revision FULL_COMMIT_SHA` pins a release. It creates a virtual environment per release and retains the previous source.

The installer writes `/usr/local/bin/anime-discovery-install` and a protected defaults file. Upgrade with:

```sh
sudo anime-discovery-install --upgrade --yes
```

Existing native settings, credentials, administrator password, and configured database path are preserved. Native configuration and database upgrades run explicitly with the services stopped, using the maintenance preview/backup contracts. Legacy configuration and databases are not imported. Use a separate fresh NextGen directory.

Fresh installations start only the API. The API and worker are separate Type=notify services with 60-second event-loop watchdogs. The worker waits for API readiness and stops when the API stops; worker failure leaves the API running. Restart the worker explicitly after API recovery. Units include configured media mount dependencies and write paths; the installer does not create, move or recursively change ownership of media directories.

Set the administrator password locally after API startup:

```sh
sudo -u anime-discovery /opt/anime-discovery/current/.venv/bin/python -m src.nextgen.api.adm set-password
```

The API itself serves the restricted `/run/anime-discovery/admin.sock`. ADM uses that socket; no management bearer token or separate admin daemon is created. For unattended first-time setup, supply a protected `--admin-password-file` with `--start api` or `--start all`. The installer passes it through stdin to ADM with `--if-unset`, so upgrades preserve an existing password. The separate optional `--webhook-key-file` seeds only an absent webhook key. Credentials are never printed or placed in command arguments.

The dashboard uses password sessions and same-origin `/api/v1` requests. Configure the exact public origin and proxy both dashboard pages and the API to the loopback listener. Configure providers in the dashboard, run worker readiness, then start/enable the worker:

```sh
sudo -u anime-discovery /opt/anime-discovery/current/.venv/bin/python -m src.nextgen check --config-dir /var/lib/anime-discovery/config --worker
sudo systemctl enable --now anime-discovery-worker.service
```

`--start preserve` is the default and retains running/stopped choices on upgrade. `--start none`, `api`, or `all` overrides it. Starting all requires worker readiness. `--enable` enables the selected component services for boot; existing enablement is retained.

If setup or activation fails, NextGen remains stopped and `installation.pending.json` identifies the candidate and previous release. Existing units are backed up under `unit-backups`. Do not point old code at a database whose schema has advanced. Correct the cause and rerun; database/source rollback is not automatic.

No live installation has been performed by the implementation tests. Follow `src/nextgen/SERVICE_SETUP.md` for host validation: password setup/login, verified webhook intake appearing in Recognized Names, worker crash isolation, API recovery followed by worker restart, mount access, and provider connectivity.
