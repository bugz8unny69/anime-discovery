# Unified database integration map

Status: foundation only, no live migration.

## Confirmed source references
- `src/legacy/controller.py` sets `DB = /var/lib/anime-discovery/controller.db` and creates `series` and `episodes`.
- `src/legacy/autobrr_discovery_inbox.py` defaults to `data_path('inbox.db')`, creates `notifications`, and explicitly rejects a path resolving to `controller.db`. That guard must be deliberately replaced after schema reconciliation.
- `src/legacy/dashboard.py` reads `data_path('inbox.db')` and imports `anime_dashboard_auth`; auth must remain functional.
- `src/legacy/migrate_inbox.py` migrates an older inbox location to `inbox.db`; do not run it blindly against the new canonical DB.
- `src/legacy/integration_schema_rehearsal.py` defines a proposed integration schema; it is not proof of a deployed migration.

## Required implementation gates
1. Enumerate all readers/writers and schema versions before changing paths.
2. Snapshot each legacy SQLite DB with the SQLite backup API, not a raw copy of an active WAL DB.
3. Create a fresh canonical DB in staging, apply versioned schema migrations, and preserve source provenance.
4. Copy actual production records, quarantine the eight known TEST fixtures, and preserve the queued Solo Leveling notification without promoting untrusted content automatically.
5. Make notification promotion idempotent with identity/episode mapping and rejection checks.
6. Migrate dashboard, webhook, identity worker, controller, and admin CLI as a coherent unit.
7. Validate old/new row counts, integrity, foreign keys, restart behavior, and rollback; switch only after tests pass.

## Current branch
`anime_db_runtime.py` is a reusable connection/transaction primitive. No production entrypoint imports it yet. No schema/data migration or VM changes have occurred.
