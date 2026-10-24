# NextGen dashboard and management authentication audit

Status: source inspection, not deployment verification (2026-10-24).

## Existing NextGen dashboard
- `src/nextgen/dashboard/assets.py` allowlists `/`, `/jobs`, `/settings`, and static CSS/JS assets.
- `src/nextgen/dashboard/static/index.html` contains Intake, Jobs, Settings, login, and job-history panels.
- `src/nextgen/dashboard/static/dashboard.js` implements job polling/actions, history, settings and private credential updates using `/api/v1/`.
- `src/nextgen/api/app.py` serves these assets through the ASGI API, and implements management routes.

## Gaps before declaring dashboard feature-complete
1. Replace management access-key login with password login, retaining cookie-session and CSRF boundaries.
2. Add Settings > Security: change password, verify current password, clear old sessions.
3. Add local `adm set-password` recovery using a permission-restricted Unix socket served by the existing API process (no extra systemd service). Verify Unix peer credentials and fail closed.
4. Use fresh NextGen configuration and existing configuration library; no legacy secrets, settings, or management-token migration. Provision dashboard password through local `adm set-password` and use the management API for subsequent configuration.
5. Remove or restrict legacy HTTP management-token authentication and the access-token mutation endpoint once password flow is operational.
6. Test unauthorized local/remote HTTP, CSRF, credential rotation, concurrent password changes, and socket permissions.
7. Compare NextGen dashboard workflows against the legacy application's complete feature inventory; presence of three tabs does not prove parity.
8. Verify real browser navigation, TLS proxy behavior, and API/worker outage presentation in an integration environment.

## Security constraint
Do not deploy the scrypt foundation as a completed authentication migration. It is currently only a helper and tests; password-backed API authentication is implemented; integration and host validation remain outstanding.

## Delivery tracker (CI intentionally deferred until requested)

- [x] Worker and API systemd readiness/watchdog implementation (previous CI #18 passed).
- [x] Source-level dashboard route and feature audit.
- [x] Versioned scrypt hash helper and initial tests (not integrated).
- [x] Add separate password-hash persistence with atomic updates and concurrent revision handling (fresh NextGen setup; no migration).
- [x] Implement password-based login and password change; invalidate all sessions on rotation (integration tests pending).
- [x] Remove management-token browser login and bearer-token bypass from administrative HTTP routes (legacy token storage cleanup pending).
- [x] Implement same-process Unix socket (0600, root/service UID), peer identity checks, and `adm set-password` (host validation pending).
- [x] Wire dashboard login and Settings > Security forms to the new API (browser testing pending).
- [x] Remove management-token bootstrap dependency; initialize fresh NextGen secrets v7, provision password via `adm set-password`, and retain independent Autobrr webhook credentials.
- [ ] Verify full legacy dashboard feature parity and worker-unavailable UX.
- [ ] Add authorization, CSRF, socket, rotation, lifecycle, and browser/API integration tests.
- [ ] Review complete diff, then ask for approval to run CI; fix failures after approval.

**Gate:** No CI trigger, merge, or deployment until the user approves CI after checklist completion.

## Confirmed scope decision

No migration from the older application is requested or authorized. Treat the legacy source solely as a reference for feature parity. A new NextGen installation starts with fresh configuration, using the existing configuration library and management API for configuration. `adm set-password` bootstraps the administrator password; it does not import legacy secrets. Do not implement migration scripts or automatic legacy-data conversion.
