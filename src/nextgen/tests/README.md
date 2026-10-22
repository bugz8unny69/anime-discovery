# NextGen tests — local, independent, batched

NextGen is a clean-slate application. Its tests live in `src/nextgen/tests/` and test only new `src/nextgen/` code. The old tests under `src/legacy/` remain intact as historical regression/reference material; they do **not** run as part of NextGen batches.

## Running tests

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
- Run the focused batch while iterating and the full NextGen batch set before requesting review/merge. Record the command and outcome in the PR description or review comment.
- Do not rewrite legacy tests to suit NextGen. Existing legacy code remains untouched. If a historical regression matters, express it as a new NextGen test of the **expected behavior**, not an imported legacy test.
- No production deploy, live acquisition, or destructive integration is part of this test runner.

**Note:** GitHub branch protection settings may still name an old required check. Removing the workflow does not automatically change those repository settings; check before merging.
