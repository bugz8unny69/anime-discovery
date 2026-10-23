# NextGen tests — local, independent, batched

NextGen is a clean-slate application. Its tests live in `src/nextgen/tests/` and test only new `src/nextgen/` code. The old tests under `src/legacy/` remain intact as historical regression/reference material; they do **not** run as part of NextGen batches.

## Commands for the later authorized testing phase

**Current policy: author and commit tests, but do not execute offline tests or
CI.** The commands below are reference instructions for later authorization.

Run from the **repository root** with Python 3.12+ (standard library only):

```sh
# Show the NextGen tests available
python -m src.nextgen.tests.run_batches --list

# Focus on the schema while working on RFC-IDENTITY-001
python -m src.nextgen.tests.run_batches --match schema

# Run all NextGen tests in groups of up to five test files
python -m src.nextgen.tests.run_batches

# Change batch size while developing additional components
python -m src.nextgen.tests.run_batches --batch-size 2

# Focus on a new component as soon as test_webhook_*.py files exist
python -m src.nextgen.tests.run_batches --match webhook
```

The runner discovers `test_*.py` files in **this directory only**, sorts them, and executes up to `--batch-size` test files in each separate Python process. It keeps running later batches when one fails, and returns an unsuccessful exit code if any batch failed. A filter matching no files is an error, not a false success.

Test JSON samples are in `fixtures/`. **Fixtures are sample data used by the tests, not code that NextGen uses to validate real identification.** The real identity completion validator is `src/nextgen/schema/anime_series.py`.

## Testing policy

- **No GitHub Actions test checks** on pushes or pull requests. The old automatic test workflow is removed in this draft branch. Tests are kept and run locally/on demand in batches, not discarded.
- Create new offline NextGen tests alongside each NextGen component. They MUST NOT depend on old runtime modules, old databases, or live services. Use temporary SQLite databases, mock providers, and sample inputs as appropriate.
- Under the current policy, record **not run** in review/PR descriptions. When execution is explicitly authorized later, run focused and complete batches and record actual outcomes.
- Do not rewrite legacy tests to suit NextGen. Existing legacy code remains untouched. If a historical regression matters, express it as a new NextGen test of the **expected behavior**, not an imported legacy test.
- No production deploy, live acquisition, or destructive integration is part of this test runner.

**Note:** GitHub branch protection settings may still name an old required check. Removing the workflow does not automatically change those repository settings; check before merging.


## Diagnostic-infrastructure cases

PR #100 adds test_messages.py, test_diagnostic_history.py,
test_diagnostic_logging.py and test_diagnostic_migration.py. These exercise
catalog coverage/locale fallback, readable safe output at all levels, reload,
sink failure, transaction coupling, audit rejection, intake/identity rollback,
independent-job correlation, and SQLite v4 fresh/sequential/failed upgrades.
They use temporary/in-memory SQLite only; no provider/runtime legacy imports.
They are authored but unexecuted. AST parsing is a syntax check, not a test run.

Job-status follow-up cases in test_job_statuses.py cover all lifecycle states,
SQL/Python activity-pair consistency, safe readable display selection, historic
activity snapshots and v4→v5 rebuild preservation/rollback/FK restoration. The
latest fresh/sequential metadata comparison now includes migration 005. Tests
remain intentionally unexecuted.

Final diagnostic review adds test_api_diagnostics.py for independent api
logging and audit attribution, v5→v6 history preservation, index/FK integrity,
version rejection and rollback. The latest sequential path includes 006.
No test execution or CI is authorized in the current phase.

Configuration-library cases in test_configuration_schema.py and
test_configuration_store.py cover versioned conversion and immutable operation
views, startup-field pinning, revision conflict, atomic publication and failure,
metadata, migration backup/preview, and safe input/filesystem validation. They
use temporary directories only. Tests and CI remain intentionally unexecuted.


Migration/admission follow-up: test_migration_runner.py and test_maintenance.py
cover versions 1–6, schema/data preservation, validated backups, stale plans,
rollback and partial-chain recovery, shared admissions, exclusive drainage,
process death, pending-state persistence and explicit resume. Tests use only
temporary databases/processes. **Authored but not executed** under current policy.


Worker naming follow-up: test_worker_naming.py covers explicit configuration
v1→v2 key/logging conversion, preserved values/revisions, mixed-name rejection,
SQLite v6→v7 historical attribution, new worker audits, version guards and
rollback. Existing runtime diagnostic tests now use worker; sequential migration
coverage includes 007 and all starting versions v1–v7. Tests remain unexecuted.


Handler history follow-up: test_handler_history.py and
test_handler_history_migration.py cover multiple/repeated calls, attempts,
start/end matching, reasons, readable labels/logging/translations, caller rollback,
v7→v8 preservation, indexes/constraints, wrong versions and migration rollback.
Sequential runner cases include every supported starting version v1–v8. The
existing jobs table is unchanged. All these tests remain **unexecuted**.


Destination settings: test_media_destinations.py covers configuration v3,
blank defaults, readable field metadata, explicit historical conversion, immutable
new-operation snapshots and invalid/overlapping roots. Authored but unexecuted.


Initial worker core: test_worker_queue.py and test_async_worker.py cover lease
fencing/recovery, concurrent claims, atomic successor facts/history, normal
defers versus failure retries, trusted adapter transaction boundaries, fresh
configuration, same-anime concurrency, maintenance and cancellation-safe drain.
All tests remain **unexecuted**; no worker or SQL has been run for verification.


Destination/worker integration review adds cases for saved roots overlapping a
still-pinned database, safe adjusted roots, post-restart views and rejecting
unsafe operation snapshots before claim while releasing maintenance admission.
These cases remain **unexecuted**, along with worker cancellation, embedded close,
historical zero-attempt recovery and oversized-payload regression cases.


Identity job: test_identify_anime_job.py covers bounded durable input, trusted
resolver injection, invalid data, series-only results, atomic identity/successor
handoff, post-commit audit receipts, review on canonical/episode conflicts,
idempotent existing snapshots, stale completion, incoming-event lease protection
and transaction rollback. test_worker_queue.py adds expected completion rejection
and invalid audit receipt rollback. Cases are authored but **not executed**.


Identity providers: test_provider_storage.py, test_identity_providers.py and
test_anidb_first_resolver.py cover SQLite v8→v9 preservation/rollback/fresh-schema
equivalence, shared concurrent request reservation, restart cooldowns, stale
publication tokens, bounded/expiring public cache, compressed response limits,
provider failure/authentication outcomes, token/response memory caching,
credential isolation, exact ID checks, AniDB-first ordering and ambiguity gates.
Sequential migration coverage includes every starting version v1–v9. HTTP tests
use fake responses only. All cases are authored but **unexecuted**; no test/CI,
SQL execution, application imports, live provider requests or deployment occurred.


Required provider configuration: test_provider_configuration.py covers explicit
v3→v4 conversion with preserved historical shapes, no enable/PIN keys, live
settings, protected credential reads/writes, presence-only results, revision
conflicts, unsafe files, publication durability and readiness before claims.
Worker/resolver cases cover key rotation, stable in-flight credentials and fresh
options for later attempts. The TVDB login case now asserts API-key-only JSON.
All tests remain authored but **unexecuted**. No imports/execution of application
code, SQL, tests/CI, live provider calls, production changes or deployment ran.


Declared release verification: test_release_verification.py covers conservative
single-episode parsing, offset/reverse/season-zero mapping, unresolved batch and
split rules, provider pagination/duplicates/cancellation, durable worker facts,
source-change rejection, stale leases and defer/review outcomes. HTTP provider
cases add official-order episode-page cache scoping and never following next URLs.
test_release_migration.py covers v9→v10 preservation, fresh equivalence, scope/
foreign-key/unique constraints and failed/wrong-version rollback. The sequential
runner covers every v1–v10 starting point. All tests are **authored but unexecuted**;
no tests/CI, application imports, SQL, live providers or media operations ran.


Trial-window policy: test_trial_policy.py covers backfill/following union,
inclusive trigger count, zero/overlap/bounds, explicit v5 conversion, live settings
for new plans, immutable anchors, season scope, concurrent creation, post-commit
readable audit, failed completion rollback and stale leases. test_trial_migration.py
covers v10→v11 preservation/fresh equivalence and wrong-version/failure rollback.
Existing migration paths include v1–v11. All tests remain **unexecuted**; no tests/
CI, application imports, SQL, live providers, acquisition/media or deployment ran.

Episode-selection regression cases reject 0/0 during conversion, snapshot
construction and settings updates, preserve saved settings on failure, and allow
6/0 and 0/1. Tests remain unexecuted under project policy.
