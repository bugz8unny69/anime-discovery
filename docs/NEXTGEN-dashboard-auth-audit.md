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
4. Version and migrate secret storage without destroying existing webhook/provider credentials; define legacy management-token migration explicitly.
5. Remove or restrict legacy HTTP management-token authentication and the access-token mutation endpoint once password flow is operational.
6. Test unauthorized local/remote HTTP, CSRF, credential rotation, concurrent password changes, and socket permissions.
7. Compare NextGen dashboard workflows against the legacy application's complete feature inventory; presence of three tabs does not prove parity.
8. Verify real browser navigation, TLS proxy behavior, and API/worker outage presentation in an integration environment.

## Security constraint
Do not deploy the scrypt foundation as a completed authentication migration. It is currently only a helper and tests; existing API authentication remains active.
