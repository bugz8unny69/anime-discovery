# Dashboard and CLI configuration rollout

This change set is deliberately staged as draft PRs #16 through #20.
No branch has been merged into `develop`; `main` and the lab VM are unchanged.

## Authentication

The old dashboard used an HTTP Basic challenge and checked `secrets.json.admin_password` directly. The HTML login now uses the pre-existing dashboard authentication module with a salted PBKDF2 password, an HttpOnly session cookie, session expiration, logout, and CSRF protection. Interactive requests are redirected to `/login`; unauthenticated API calls receive a JSON 401. The webhook token is never accepted as an administrator login.

Once a hashed password exists it is authoritative. A legacy administrator password is migrated once when the hash store is missing. New credentials should be changed with the local CLI, not by editing the old plaintext field manually. Run `python3 src/legacy/anime_dashboard_auth.py passwd` locally for password recovery. Session rotation revokes existing logins.

For a reverse proxy, preserve the host/redirect paths; terminate TLS and sanitize `X-Forwarded-Proto: https`. Do not add a second HTTP Basic authentication challenge in the proxy. Real proxy and direct-service tests remain necessary before publishing.

## CLI

```sh
python3 src/legacy/anime-discovery-admin.py settings show
python3 src/legacy/anime-discovery-admin.py settings show --json
python3 src/legacy/anime-discovery-admin.py settings set-secret sonarr_api_key
python3 src/legacy/anime-discovery-admin.py settings set-secret sonarr_api_key --clear
python3 src/legacy/anime-discovery-admin.py settings configure-credentials
python3 src/legacy/anime-discovery-admin.py settings configure-integration shoko
python3 src/legacy/anime-discovery-admin.py setup
python3 src/legacy/anime-discovery-admin.py setup --reconfigure
```

The secret editor prompts without placing values in process arguments or shell history. Enter keeps the existing secret; `--clear` requires the explicit word `CLEAR`. Clearing enabled integration credentials may be refused during validation. Dashboard administrator passwords must be rotated rather than cleared.

The settings summary reads persisted values, not a live snapshot of worker state. Sensitive values appear only as **Set / Not set**. Integration prompts display existing non-secret values as defaults and preserve blank answers.

## Shared configuration / dashboard

Both the CLI settings writer and the admin-only `/api/settings` use a shared validation and atomic JSON settings writer. Settings Save & Apply persists safely and marks service restart required; it does not falsely claim every worker reloads dynamically. The five dashboard integration cards are Jellyfin, Sonarr, Shoko, Autobrr and NTFY. Credential replacement uses the same secret editor and the server never sends stored credentials back to the browser.

The initial configuration is performed only by the local CLI. The dashboard cannot be claimed remotely while uninitialized.

## Not yet production validated

Mock/offline tests cover login, CLI secret handling, settings persistence, and the basic setup wizard. Remaining checks include direct and reverse-proxy browser tests with TLS, full credential migration on an existing installation, actual integration connectivity/test-notification controls, unsaved-change warnings and service-account permission verification. These draft changes must not be released without review.
