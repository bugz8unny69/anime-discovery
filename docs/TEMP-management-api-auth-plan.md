# TEMP: Management API authentication and CLI plan

> **Status: deferred design note, not implemented.** Remove this document after the implementation and permanent documentation replace it. Do not merge the experimental socket-only approach as the final design.

## Why this exists

The management API serves **both** dashboard Settings actions and the local `adm` CLI. Restricting the entire management API to a Unix socket would break dashboard management. Likewise, trusting arbitrary HTTP loopback clients would be unsafe. Preserve one shared set of management operations with distinct, explicitly authorized transports.

## Intended interfaces

- **Dashboard:** HTTPS via the existing loopback HTTP API/reverse proxy. Admin logs in with a password; the API establishes a session with appropriate CSRF protections. Settings changes and Apply use authenticated management endpoints.
- **Local CLI (`adm`):** Connect to a restricted Unix-domain socket, for example `/run/anime-discovery/admin.sock`. Socket access must be limited to the service account and explicitly trusted administrators (mode `0660`, appropriate ownership and parent-directory permissions). Check peer credentials where supported; never equate loopback TCP with trusted local identity.
- **Autobrr webhook:** Remains available through its intended HTTP route with a separate webhook credential; it must not gain administrative privileges.

## Password operations

- Dashboard Settings → Security: authenticated **change password**; verify current password and validate the new one.
- `adm set-password`: **initial password setup and recovery**, through authorized local socket access; no old password required. Should not require root if the invoking user is authorized to connect.
- Passwords must be stored using a modern password hash, not plaintext or reversible secrets. Never log passwords, authentication headers, or recovery input. Define session invalidation after password changes and protect against concurrent changes.

## Architecture and ordering

1. **First:** settle and implement the management supervisor / process lifecycle design. The present NextGen branch runs API and worker as distinct systemd services with `Restart=on-failure`; async tasks and threads exist *within* those processes. Whether the future supervisor uses child processes or async tasks must be decided against actual worker/API shutdown behavior.
2. **Later:** attach the local Unix socket to the API component under the agreed supervisor architecture, without introducing an additional systemd service solely for the socket.
3. **Later:** implement password login, dashboard password change, `adm` local recovery, authorization boundaries, and tests. Retain dashboard and webhook HTTP connectivity.
4. **Then:** return to the installer, integrating the final supervisor service and administrative CLI.

## Validation checklist for the deferred work

- Unauthorized HTTP callers, including loopback clients, cannot mutate settings or reset passwords.
- Dashboard sessions and CSRF protections work for management mutations.
- Authorized socket clients can use `adm`; untrusted users cannot.
- Root can use the socket; permitted group members can connect with `0660`, subject to directory permissions.
- Password reset invalidates existing sessions; no password or token is exposed in logs.
- Dashboard, webhook, worker, shutdown, and restart behavior remain functional.

## Experimental PR warning

The initial draft PR #140 introduced a **separate systemd admin service/socket** and a socket-activated API mode. That approach predates this clarified architecture and should be replaced or discarded rather than merged unchanged.
