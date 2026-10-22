# ReleaseRecord v1 — canonical contract

**Status:** initial, offline-only contract. **Version:** 1. This package does not alter existing application behavior or storage.

- **One schema:** `ReleaseRecord` keeps one shape from receipt through export. Later stage sections remain null until known. Component results do not require new record formats.
- **Every field is documented:** Python dataclass metadata includes `meaning`, `reason`, `owner`, `available`, and `trust`; tests enforce all five.
- **Source boundaries:** receipt data is untrusted; identity verifies exact AniDB/TVDB series, season and episode mapping using current proven rules; staging paths must always be revalidated by the filesystem component. This schema **does not itself verify** a claimed identity, authorize acquisition or sanitize paths.
- **Jobs stay independent:** the root release trace is `AD-<notification_id>`, but individual execution job IDs live with their stage results/job tables, not as an alternate release identity.
- **Compatibility:** unknown serialized fields and incompatible versions fail closed. Optional sections may be absent/null in incoming v1 records. A future incompatible meaning/type/trust change requires v2 and explicit migration/adapter tests.
- **Persistence later:** this is a read/transport contract; existing normalized SQLite tables remain authoritative. Next milestone: read-only assembler backed by those tables, followed by component-specific contract adapters.
- **Fixtures:** v1 intake-only and verified-season fixtures are permanent regression inputs. Add documented negative cases and legacy behavior-equivalence fixtures as stages are extracted.

No production migration, new worker, live integration, HookRegistry, TVDB reconciliation rewrite, or Jellyfin NFO changes are included.
