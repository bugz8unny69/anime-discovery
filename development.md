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

## SSH Git access

The operator reports uploading a public SSH key to GitHub; **verify the key used by the VM works** before attempting clone/pull. The private key must remain on the VM (or authorized SSH agent). A GitHub *account* SSH key and a *repository deploy key* are different options; deploy keys may be configured read-only. Do not display, copy, or commit private key contents.

Run as the existing application checkout/service owner, **not root by default**:

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
sudo python3 src/legacy/anime-discovery-admin.py upgrade
```

This path is designed for fast-forward updates from `origin/develop` with an online-safe SQLite backup, service restart and code rollback on restart failure. It does **not** make a draft PR safe for production. Get explicit operator approval before running it; confirm the checkout is appropriate and tests passed.

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
- `.github/workflows/publish-archive.yml`: **currently** runs on every push to `develop` and manual `workflow_dispatch`; compiles source; packages both `.tar.gz` and `.zip`; emits SHA256SUMS; and creates a `build-<12-character-commit-sha>` GitHub release.
- **Desired next change (not yet implemented):** stop packaging on every `develop` push. Produce release packages only after explicit approval, with a separately reviewed versioning design. Preserve test checks and existing published releases. Do not claim this policy is already enforced.
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
2. Query GitHub for current `develop`, PR #66, PR #67 and CI; documentation is not proof that a PR has merged or a deployment occurred.
3. Ask before performing **live** deployment, SQLite migration, service restart, media deletion or torrent cleanup.
4. Keep requested work narrow. Current priority: stop automatic package builds from `develop` in a small separate PR, retaining manual release capabilities and testing.
5. Report separately: coded, PR-open, CI-verified, merged, and deployed. Never conflate them.

**Supporting project notes** (uploaded in conversation; not necessarily in repository): `anime-discovery-pr-handoff-2026-10-21.md`, `gemini-code-1792038645145.md`, `homelab-network-topology.md`, and `server-nas-network-build.md`. Check up-to-date runtime settings against historical notes.
