# Source baseline and credential review

Review date: 2026-10-18. Input: user-supplied `anime-discovery-current.tar.gz`.

## Inventory
- 238 regular archive entries; 198 top-level Python files.
- Six embedded `.tar.gz` historical batch archives.
- Historical `.before-*` snapshots, staged release directories, candidate modules, integration rehearsals, and test fixtures coexist with potential runtime modules.
- Source import to GitHub **not yet completed**; repository documentation is a checkpoint, not an application checkout.

## Credential checks
- The prior machine-readable scan reported no recognized private keys, GitHub tokens, AWS access keys, or confirmed hard-coded service credentials.
- The scan logged potential patterns in HTTP authorization-header construction, config getters, and test fixtures; these are not by themselves leaked credentials.
- A second direct scan of top-level Python files for literal assignments to password/API key/secret/token found matches in test fixtures (e.g. `admin-token`, `decision-secret`, `SHOULD_NOT_LEAK_123`) and no production-source literal assignments matching that specific pattern.
- **Not a guarantee**: pattern-based scans can miss real secrets, dynamic files, and undocumented credential formats. Review the final included file set before pushing.

## Exclude from first source baseline
- All six nested release tarballs, release packaging directories and duplicate historical snapshots.
- Production databases, WAL/SHM, configs with credentials, downloaded data, local virtualenvs, backups, compiled Python.
- Do not exclude active modules solely based on a candidate-like filename until entrypoint/dependency analysis is complete.

## Next gate
Identify exact runtime entrypoints and direct/dynamic imports, build an explicit allowlist of baseline source files, and verify that no credential values are present in those files. Commit a reviewed baseline to a development branch and validate tests before considering any release.

No deployment or production VM mutation has occurred.
