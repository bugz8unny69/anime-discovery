# Anime Discovery — development and homelab guide

> **Purpose:** Ground future development chats in verified repository paths, host context, and safe commands. This document is not permission to deploy, delete media, alter production SQLite, or merge a PR.
>
> **Last reviewed:** 2026-10-21. Runtime `/etc/anime-discovery/settings.json` remains authoritative. Infrastructure notes include historical and partially verified details.

## Repository and branching

- Private GitHub repository: `bugz8unny69/anime-discovery`
- Git SSH remote: `git@github.com:bugz8unny69/anime-discovery.git`
- Integration branch: `develop`; repository default is `main`. Do not accidentally base work on `main`.
- Develop locally on dedicated feature branches and open PRs to `develop`.
- Never assume a PR merge deploys to the VM.
- As of this guide, PR #66 (`feat/checkpoint-recovery-review-cleanup`) is draft checkpoint recovery; PR #67 (`feat/application-wide-diagnostics`) is draft diagnostics. **Diagnostics first; do not merge either without passing tests.** Check live GitHub state on each new conversation.
- No Docker deployment is used. Native Python/systemd on the Ubuntu `torrents` VM is the current approach.

## Linux users, permissions, and SSH identity (read before commands)

**Default:** operate on the Anime Discovery Git checkout as its dedicated service/checkout account, typically `anime-discovery`, **not root**. Confirm the real account before running anything; names in notes are not proof of the VM's current service identity:

```bash
systemctl show anime-discovery.service -p User -p Group
stat -c '%U:%G %n' /opt/anime-discovery /opt/anime-discovery/.git
id anime-discovery
```

If `User=` is empty, the systemd unit may run as root; do not guess. The Git checkout owner and the systemd service user can differ. **Make the checkout owner the Git operator**; use the service user for application commands only if permissions allow. A new conversation should read these commands' output before proposing ownership changes.

### Run Git as the checkout owner

Example **only if the checkout is owned by `anime-discovery`**:

```bash
sudo -H -u anime-discovery -- git -C /opt/anime-discovery status --short --branch
sudo -H -u anime-discovery -- git -C /opt/anime-discovery fetch origin develop
sudo -H -u anime-discovery -- git -C /opt/anime-discovery log -1 --oneline
```

`sudo -H -u anime-discovery` sets the appropriate home for SSH identity/config; `runuser -u anime-discovery -- ...` is an alternative *from root*, but do not assume it sets `HOME` to the intended value in every shell/sudo arrangement. Avoid `sudo -E` or the operator's `suroot='sudo -E zsh'` for Git: preserving `HOME=/home/sysadmin` while running as root caused SSH-key confusion.

The existing checkout was reported newly cloned from GitHub. If the root user cloned it, Git's files belong to root, **regardless of which account's SSH key authenticated**. Git writes and ownership are governed by the local process user, not by GitHub username or deploy-key identity. Do **not** blindly run `chown -R` on `/opt`; choose one checkout owner and review a limited ownership adjustment for `/opt/anime-discovery` if needed.

The reported deploy key filename was `/home/sysadmin/.ssh/anime_discovery_deploy` (lowercase); that private key was usable by explicit `ssh -i`. This does **not** establish that `anime-discovery` can use it. Provision and test read-only GitHub SSH access for the *actual checkout owner* without pasting or committing the key:

```bash
sudo -H -u anime-discovery -- ssh -T git@github.com
```

GitHub's successful SSH authentication greeting can still exit 1; verify the text. Keep permissions to the private key restrictive, and verify server host keys.

### Run administration at the privilege it requires

**Not every admin subcommand can run as the service user.** Settings and secrets under `/etc/anime-discovery` may be writable by their owner (often the application account), but check exact ownership and mode without printing secrets:

```bash
stat -c '%U:%G %a %n' /etc/anime-discovery /etc/anime-discovery/settings.json /etc/anime-discovery/secrets.json /var/lib/anime-discovery
```

For a settings command that the application account is authorized to perform, for example:

```bash
sudo -H -u anime-discovery -- python3 /opt/anime-discovery/src/legacy/anime-discovery-admin.py settings migrate
```

`settings migrate` above is preview-only (no `--apply`). For writes, use the owner authorized for the settings/secrets files; do not broaden filesystem permissions or make secrets world-readable to avoid an error.

**Git upgrade requires systemd service control and SQLite backup access.** The current `anime_admin_upgrade.py` deliberately runs its Git subprocesses as the **checkout owner when the admin CLI is started as root**, while `systemctl stop/start` and backup creation remain privileged. Therefore the documented live upgrade is generally:

```bash
sudo -H python3 /opt/anime-discovery/src/legacy/anime-discovery-admin.py upgrade
```

The admin command uses a pinned GitHub SSH remote (`git@github.com:bugz8unny69/anime-discovery.git`) on `develop` and currently does not fall back to HTTPS. **The checkout owner's GitHub SSH key must work** for this command, even though the Python wrapper runs as root. Don't blindly replace the command with `sudo -u anime-discovery ... upgrade`: the Git step might work while systemd control or database backup fails. Running the *whole* upgrade as the service user requires a separately reviewed privilege mechanism (such as tightly scoped sudo/polkit), not a blanket change.

If a command fails with permission denied, report the command and `stat`/service-user results first; don't rerun everything as root or relax permissions recursively.

## SSH Git access

The operator reports uploading a public SSH key to GitHub; **verify the key used by the VM works** before attempting clone/pull. The private key must remain on the VM (or authorized SSH agent). A GitHub *account* SSH key and a *repository deploy key* are different options; deploy keys may be configured read-only. Do not display, copy, or commit private key contents.

Run as the verified Git checkout owner (typically `anime-discovery`), **not root by default**:

```bash
ssh -T git@github.com
```

An SSH greeting confirms authentication (GitHub may return exit code 1 despite successful authentication). For a first-time host-key prompt, verify GitHub's published SSH host-key fingerprint independently before accepting; never disable host-key checking.

### New checkout only

**Check that `/opt/anime-discovery` is absent first. Never clone over an existing installation.** The repository README documents:

```bash
git clone --branch develop git@github.com:bugz8unny69/anime-discovery.git /opt/anime-discovery
cd /opt/anime-discovery
```

Do **not** run `deploy/install-homelab.py` against an already installed service merely to update code. A fresh installation requires reviewing the README and the existing config/database safeguards.

### Existing checkout: inspect without changing state

```bash
cd /opt/anime-discovery
git remote -v
git status --short --branch
git branch --show-current
git log -1 --format='%h %s'
git fetch origin develop
git log --oneline HEAD..origin/develop
```

Before considering a live update, inspect the actual checked-out branch, working tree, target SHA, and PR status. Avoid overwriting local changes.

### Live upgrade — prefer the built-in backed-up path

The README documents this for an **existing Git checkout**:

```bash
cd /opt/anime-discovery
sudo -H python3 src/legacy/anime-discovery-admin.py upgrade
```

This path is designed for fast-forward updates from the fixed GitHub SSH repository's `develop` branch with an online-safe SQLite backup, service restart and code rollback on restart failure. It does **not** make a draft PR safe for production. Get explicit operator approval before running it; confirm the checkout is appropriate and tests passed.

For fast PR validation, prefer offline tests in a disposable checkout/temp DB, or an isolated test VM; do not switch the live service to a draft branch or point tests at production media/database.

### Read-only service inspection

```bash
sudo systemctl status anime-discovery.service --no-pager
sudo journalctl -u anime-discovery.service -n 100 --no-pager
```

Do not paste credentials or unredacted sensitive journal data into chat.

## VM, configuration, and storage reference

| Purpose | Path or host | Confidence / caution |
| --- | --- | --- |
| Application host | `torrents` Ubuntu VM | Infrastructure notes; verify current VM |
| Git checkout / installation | `/opt/anime-discovery` | Repository README |
| Settings | `/etc/anime-discovery/settings.json` | Authoritative runtime values |
| Secrets | `/etc/anime-discovery/secrets.json` | **Never dump or paste contents** |
| Persistent SQLite database | `/var/lib/anime-discovery/anime-discovery.db` | Operator-confirmed |
| Persistent state/cache | `/var/lib/anime-discovery/` | Retain; never casually wipe |
| Torrent download root | `/mnt/media/Torrents/anime/` | Historical config; check `storage.download_root` |
| Torrent parent | `/mnt/media/Torrents/` | **Case-sensitive** |
| Anime dataset | `/mnt/media/Anime/` | Separate TrueNAS dataset, 100 GB quota in notes |
| App staged/trial root | `storage.trial_root` in settings | **Not proven equal** to `/mnt/media/Anime/` |
| TV series and movies | `/mnt/media/TV Shows/`, `/mnt/media/Movies/` | Documented mounts, not confirmed container mappings |
| TrueNAS NFS export | `/mnt/store/media` on TrueNAS, `/mnt/media` on Linux clients | Infrastructure notes |
| Media center | `media-center` Ubuntu VM, Jellyfin and Shoko | Infrastructure notes |
| Sonarr | Separate Arr host (`sonarr.arr.internal` historically) | Verify endpoint from runtime config |
| qBittorrent/autobrr | `torrents` VM (`torrents.int.lhprojects.net` historically) | Verify runtime endpoint |

TrueNAS/NFS paths are separate from actual qBittorrent torrent `save_path`, the app's staging root, and Sonarr-managed library files. Do not assume their equivalence.

**Safe non-secret config path query on the `torrents` VM:**

```bash
sudo python3 - <<'PY'
import json
with open("/etc/anime-discovery/settings.json") as f:
    cfg = json.load(f)
for section, key in (
    ("daemon", "database_path"),
    ("storage", "download_root"),
    ("storage", "trial_root"),
):
    print(f"{section}.{key} = {cfg.get(section, {}).get(key, '<missing>')}")
PY
```

Network context: OPNsense segments 14 VLANs; TrueNAS serves NFS; DATA VLAN 14 is documented for MTU-9000 storage, while STORAGE is VLAN 7. Exact VM network mapping and the TrueNAS IPs require runtime verification. No networking changes are part of normal app development.

## Current GitHub Actions and packaging (verified on develop, 2026-10-21)

- `.github/workflows/anime-python-tests.yml`: `push` on `develop`, `feature/**`, `fix/**`; `pull_request` to `develop`; and manual `workflow_dispatch`. Uses `ubuntu-latest`, Python 3.12, `compileall`, and a lengthy explicit offline `unittest` suite. Be mindful that push and PR events can duplicate work.
- `.github/workflows/publish-archive.yml`: PR #70 removed the automatic `develop` push trigger; only `workflow_dispatch` remains. Verify availability on the repository's default branch before relying on manually started packages. Packages remain `.tar.gz`/`.zip` with SHA256SUMS and `build-<12-character-commit-sha>` release naming.
- **Next release improvement:** independently review manual publishing, explicit approval, and SemVer (current automatic package trigger is already removed). Preserve test checks and existing published releases.
- No Docker or GHCR pipeline is planned.
- Never overwrite immutable release tags; inspect existing tags/version references before adopting SemVer.
- GitHub Actions quota was reportedly exhausted; earlier PR #66/#67 runs failed without accessible job logs. Re-check billing/CI rather than attributing these failures to Python without evidence.

## Recovery and cleanup safety

Architecture: **Checkpoint → Validate → Resume; or Cancel → Clean up abandoned resources → Preserve history.**

- A verified staged episode is completion evidence, not trash. Repair/reconcile NFO/SQLite after interrupted finalization.
- qB ownership is distinct from release identity, notification, job and staged episode provenance.
- Never remove live torrents, torrent payloads, verified staged media, Sonarr-managed files, or reset SQLite without an explicitly reviewed plan and authorization.
- Use mock qBittorrent/Sonarr and temporary directories/databases for automated tests.
- Cancel must never be reported as cleanup completed unless the resources have actually been verified/cleaned. Preserve external/shared torrents and immutable canceled history.
- The incident involving Cyberpunk Edgerunners `LOOKUP_AttributeError` needs tracebacks/reproduction, not speculative changes.
- PR #66 is unfinished and includes recovery and cleanup work; review its current diff and CI before continuing it.

## Instructions for a new development chat

1. Read this `development.md`, `README.md`, current workflow YAMLs and the relevant handoff document (if attached).
2. Query GitHub for current `develop`, PR #66, PR #67, PR #69, PR #70 and CI; documentation is not proof that a PR has merged or a deployment occurred. On the VM verify checkout owner and systemd user before issuing writable commands.
3. Ask before performing **live** deployment, SQLite migration, service restart, media deletion or torrent cleanup.
4. Keep requested work narrow. Automated `develop` package publishing was removed by PR #70; next priorities are service-account ownership/permissions and validated SSH upgrades.
5. Report separately: coded, PR-open, CI-verified, merged, and deployed. Never conflate them.

**Supporting project notes** (uploaded in conversation; not necessarily in repository): `anime-discovery-pr-handoff-2026-10-21.md`, `gemini-code-1792038645145.md`, `homelab-network-topology.md`, and `server-nas-network-build.md`. Check up-to-date runtime settings against historical notes.
