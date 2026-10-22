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
