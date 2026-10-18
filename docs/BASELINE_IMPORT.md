# Reviewed source baseline import

Status: awaiting first source push. This branch currently contains documentation only.

The reviewed source archive is `anime-discovery-reviewed-baseline.tar.gz` (provided in the project conversation). It includes `source/` with 198 top-level Python files and a manifest. All 198 files passed Python AST parsing; this does not establish runtime correctness.

## One-time import from your workstation

Use the accompanying `import-reviewed-baseline.sh` script and archive downloaded from ChatGPT. The script clones this private repository, checks out `develop`, copies reviewed source files to `src/legacy/`, checks the Git staged diff for suspicious paths, then asks before committing and pushing. It does not touch the production VM.

Do not import historical nested tarballs, runtime state, production secrets, database files, or local virtual environments.

After the first push, future development can be done against versioned GitHub source, with pull requests to `main`.

## Runtime caveat

`src/legacy/` is a preservation namespace for the first source import. Do not assume it is directly runnable from that location: legacy entrypoints/imports may require a future coordinated layout migration. No production installer should be built from this snapshot until runtime mapping and integration tests pass.
