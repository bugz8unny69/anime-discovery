# Security and data boundaries

- Keep this repository private.
- Never commit production API tokens, webhook secrets, passwords, private keys, auth cookies, or local credential files.
- Do not commit production SQLite databases, WAL/SHM files, downloaded media, torrent files, or full VM backups.
- Use sanitized examples and synthetic secrets in tests.
- Review historical source snapshots for embedded credentials before importing.
- The repository does not grant access to the production VM.
- Destructive qBittorrent operations must require verified ownership and fail closed on uncertainty.
- Dashboard rejection must not delete unrelated files.
