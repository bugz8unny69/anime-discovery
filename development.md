# Anime Discovery — development and homelab guide

> **Purpose:** Ground future development chats in verified repository paths, host context, and safe commands. This document is not permission to deploy, delete media, alter production SQLite, or merge a PR.
>
> **Architecture handoff updated:** 2026-10-22. Historical implementation details below may describe the existing legacy application rather than the planned replacement. **Last infrastructure review:** 2026-10-21. Runtime `/etc/anime-discovery/settings.json` remains authoritative. Infrastructure notes include historical and partially verified details.

## Architecture handoff — clean-slate next generation (2026-10-22)

**Decision:** Stop incremental patch-driven feature expansion of the legacy runtime and design a next-generation implementation in `src/nextgen/`. **Start the architecture fresh but reuse verified algorithms, adapters, tests, and the already-merged daemon job infrastructure.** This is a staged replacement, not permission to delete legacy code or migrate production. Existing `src/legacy/` continues to function unchanged until a separately authorized cutover. The next generation must be independently testable before any deployment.

### Why we changed direction

Two weeks of implementing notification, identity, acquisition, staging, Jellyfin, Keep and Sonarr workflows uncovered excessive cross-component coupling. Improving one part often required changes across several modules, and patch fixes accumulated. The desired solution is **one stable, versioned release-record contract plus explicitly bounded components**, not a dynamic plugin system, weighted provider voting, or runtime hook registration.

We considered serialized hooks, registration logs, multiple provider evidence hooks, authoritative merging, and postponing TVDB reconciliation until Sonarr export. Those were **explorations, not adopted architecture**. In particular, postponing TVDB is unsafe without redesigning staging: `anime_trial_staging.py` and `anime_nfo_repair.py` currently require a verified TVDB ID for Jellyfin NFO generation and path/identity validation. Preserve the proven AniDB-first lookup with exact AniDB↔TVDB series, season and episode verification rather than replacing it with a simplistic score.

### End-to-end lifecycle and ownership

1. **Webhook intake (Autobrr):** validate and deduplicate source/GUID; persist immutable release facts and a stable notification/correlation reference. Webhook release names are untrusted hints, not episode proof.
2. **Identity component:** use existing AniDB-based identity, TVDB, Anime-Lists and exact season/episode reconciliation logic. Preserve sequel, cour, split-season, batch, ambiguous mapping and provider-failure safeguards. No inferred TVDB season 1, no implicit AniDB/TVDB episode-number match. Emit a verified result or a clear RETRY/REVIEW/exclusion decision.
3. **Acquisition component:** consume only verified/eligible identity and policy, authorize downloads through existing ownership, duplicate, size and Japanese+English audio safeguards. Keep integrations encapsulated.
4. **Staging component:** consume verified identity, media and configured storage policy; securely validate roots, symlinks, ownership/permissions, paths, NFO and episode metadata at point of use. Supplying a path in the record never makes it trusted. Publish to Anime Trial/Jellyfin only on successful checks.
5. **Human evaluation:** user reviews staged content, chooses **Keep** or **Reject**; never implicitly Keep.
6. **Keep/Sonarr export:** require explicit Keep and the existing verified TVDB/season/episode identity; retain import safeguards, idempotency and protective cleanup behavior. Reject follows existing safe ownership/cleanup rules.
7. **Operational history:** reconstruct activity using the stable notification trace across independently completed jobs, stages, retries and review choices.

### One canonical release record; progressively populated

Use **one versioned application-level schema for the whole journey**, not mutually incompatible payload shapes at each stage and not one enormous database table. At intake, many later fields are absent; components fill only fields they own and persist results durably. A restart reassembles the record from existing normalized SQLite tables. Components use narrow validated views of the same canonical record; they do not need to receive or understand every field.

Proposed groups (contract design to be implemented/tested, not an existing deployed schema):
- `schema_version`; `notification_id` / stable `trace_id`; source, GUID, received time, release name, info hash and immutable raw-intake references where necessary.
- `identity`: AniDB/TVDB IDs, verified exact season/episode/episode ID, independently obtained mapping provenance, decision, explicit uncertainty and episode/evaluation window.
- `acquisition`: authorization, owned torrent/download references, downloaded file identifiers, media/size/audio evidence and job outcome.
- `staging`: verified staged path, NFO result, secure storage evidence and Jellyfin readiness.
- `evaluation`: review status and explicit Keep/Reject decision.
- `sonarr`: protected export result and external identity/import records.

**Ownership:** intake writes intake facts; identity writes verified identity; acquisition writes acquisition/media evidence; staging writes staging metadata; review writes human decision; Sonarr adapter writes import outcome. Every consumer validates prerequisites and fails closed on missing/conflicting inputs. Existing immutable verified decisions may not be silently overwritten by a later component. Extending a component's private implementation should not affect siblings; changing the public record contract requires deliberate schema versioning and contract/regression tests. The coordinator changes only for new workflow transitions, not internal component improvements.

### Coordinator, durable jobs and static boundaries

The existing `src/legacy/anime_async_daemon.py` job infrastructure is **already on develop**: `daemon_jobs` provides SQLite-backed work, leases, retries and independent completion. Do not reinvent it. Future orchestration should be small: choose a stage, load/validate the canonical record, invoke its explicit component interface, persist result and the next durable job/handoff transactionally where appropriate. Each stage has one clear owner; no runtime hook discovery/registration, interchangeable verifier hooks, dynamic priority graph, or arbitrary external plugin mutation. “Detach a component” means replace its implementation behind a stable contract, not disable mandatory identity/audio/Keep security checks. Simple stage-by-stage calls are preferred over a generic orchestration framework.

Notification history must never be deleted as a result of job migration. `notifications` is the persistent incoming release/Series History; `unified_identity_checks` holds legacy identity evidence and independent retry timing; `daemon_jobs` schedules executable work; `episode_dispatch` records verified episode dispatch. **Do not run two competing retry schedulers during a future identity-worker cutover.** The existing polling monitor remains intact until tested migration, rollback and one-time backfill of outstanding pending notifications are separately approved.

### Tracing and dashboard

Use a stable, Postfix-like correlation identifier: `AD-<notification_id>` follows notification-related processing and jobs; `AJ-<root job id>` covers standalone work. Preserve distinct job IDs for attempts, leased work and handoffs. Reuse `anime_diagnostics.event` and the systemd journal with redacted/allowlisted fields; store bounded structured lifecycle events durably in existing SQLite for the Activity/History dashboard, because journal retention is not permanent. Log stage/job start and finish, decision/status, retry or review outcomes, failures and safe reason codes. Avoid raw tokens, credential-bearing URLs and potentially sensitive payloads. The dashboard should display a copyable trace ID, job IDs and an ordered history, eventually searchable without SSH. **Current PR #91 provides only the low-level job tracing foundation; its dashboard timeline is not yet implemented.**

### Reuse and migration guardrails

- Reuse proven algorithms and regression fixtures from `src/legacy/`, rather than translating/reimplementing working AniDB, TVDB and Anime-Lists logic. Extract behind stable contracts after behavior-equivalence tests.
- Keep Jellyfin NFO metadata identity and safe filesystem behavior intact. A verified TVDB ID currently participates **before** Sonarr Keep, including staging, so no deferred TVDB reconciliation without a distinct design/testing PR.
- Preserve size limits, verified Japanese+English audio, eligibility window, exact season/episode mapping, explicit Keep, torrent/media ownership rules, and manual review/retry semantics. Uncertain evidence must not become implicit approval.
- Existing tests, especially `test_anime_unified_identity_monitor.py` and `test_anime_episode_crossref.py`, are release gates for sequel seasons, Anime-Lists mapping absence, duplicate crossrefs, explicit verified episode IDs and fail-closed outcomes.
- Design first; implement a read-only canonical-record assembler against existing SQLite tables, then add schema contract tests and boundary fixtures. Migrate one isolated component at a time, compare decisions/outputs against legacy, and introduce durable handoff tests (idempotence, crashes, restarts, retry ownership) before moving runtime entry points.
- Keep new code and tests under `src/nextgen/` (see README); do not bulk-move legacy files just for appearances. Avoid parallel production runners until an explicitly approved cutover plan.
- Never alter live VM, service state, databases, torrents/media, or merge/deploy based on this note.

### PR and handoff status as of 2026-10-22

- **PR #89:** closed without merge; earlier identity-worker migration, dynamically registered hooks and dashboard tracing experiment superseded. Historical reference only.
- **PR #91:** draft `infra/component-boundaries-tracing-20261022` → `develop`. Extracts bounded job trace history and logger correlation and documents static boundaries; still requires CI/behavior review. This handoff documentation and `src/nextgen/` skeleton are added to its branch. **Not merged or deployed.**
- **PR #90:** separate draft for future manual/approval/automatic discovery and backfill design. Do not re-enable automatic Prowlarr backfill in the infrastructure rewrite.
- **Next chat's focused task:** design `ReleaseRecord v1` field ownership, source-of-truth mapping, required data by stage, immutable provenance, read-only assembler and contract tests; then decide the first real component extraction. Resist an entire-runtime rewrite in one PR.

---

## Repository and branching

- Private GitHub repository: `bugz8unny69/anime-discovery`
- Git SSH remote: `git@github.com:bugz8unny69/anime-discovery.git`
- Integration branch: `develop`; repository default is `main`. Do not accidentally base work on `main`.
- Develop locally on dedicated feature branches and open PRs to `develop`.
- Never assume a PR merge deploys to the VM.
- Historical note: PR #66 (checkpoint recovery) and PR #67 (diagnostics) were earlier development tracks. Their status in older handoffs may be stale; always query GitHub before treating any PR as open, merged, or deployed.
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

### Live upgrade — standalone Git bootstrapper

After its PR is reviewed and merged, install the independent upgrader once:

```bash
sudo -H python3 /opt/anime-discovery/deploy/anime-discovery-upgrade.py --install
```

Then use:

```bash
sudo -H /usr/local/sbin/anime-discovery-upgrade
```

Run as root for SSH authentication, backup, and systemd control. The tool
reconciles checkout ownership to `anime-discovery` before service startup.
It uses the pinned private GitHub SSH source, applies fast-forward-only Git
updates and stores recovery state outside Git. Only run on live VM after
approval, code review and passing CI.

The general admin CLI no longer offers `upgrade`; the old local
ZIP/tar.gz upgrader has been deleted. Future **direct online archive**
download support may be designed later but is not implemented or configured.
Do not pass a local archive to the standalone Git updater.

For fast PR validation, prefer offline tests in a disposable checkout/temp
DB or an isolated test VM; do not switch the live service to a draft branch.

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

- `.github/workflows/anime-python-tests.yml`: after merged PR #79, `push` on `develop` only, `pull_request` targeting `develop`, and manual `workflow_dispatch`. It no longer automatically runs the full suite for each `feature/**` or `fix/**` branch commit. Uses `ubuntu-latest`, Python 3.12, `compileall`, and the explicit offline `unittest` suite. Concurrent runs are scoped by workflow + event + PR number/ref, with `cancel-in-progress: true`. PR and post-merge push checks remain separate.
- `.github/workflows/publish-archive.yml`: PR #70 removed its push trigger; a manually dispatched historical release-publishing workflow remains. It is **not** used for VM Git upgrades.
- **Desired next change (not yet implemented):** stop packaging on every `develop` push. Produce release packages only after explicit approval, with a separately reviewed versioning design. Preserve test checks and existing published releases. Do not claim this policy is already enforced.
- No Docker or GHCR pipeline is planned.
- Never overwrite immutable release tags; inspect existing tags/version references before adopting SemVer.
- Historical GitHub Actions quota and anomalously long check incidents are not evidence of a current quota or failed tests. Inspect each workflow trigger, *individual PR/push check*, duration, job logs and GitHub billable usage independently. A successful push check does not prove the separate PR check passed.

## Standalone Git upgrade bootstrapper (proposed; install only after PR review)

The independent `deploy/anime-discovery-upgrade.py` uses Python's standard library, Git and systemd; it does **not** import the Anime Discovery dashboard or daemon. Its installed copy lives outside the app at `/usr/local/sbin/anime-discovery-upgrade`. Git is kept **in-place**, not extracted to a second application directory.

After this PR is merged, explicitly install the reviewed bootstrapper **once**:

```bash
sudo -H python3 /opt/anime-discovery/deploy/anime-discovery-upgrade.py --install
```

Then future Git upgrades may run:

```bash
sudo -H /usr/local/sbin/anime-discovery-upgrade
```

The general `anime-discovery-admin.py` intentionally has **no** `upgrade` command; use the standalone executable for Git SSH upgrades. Local ZIP/tar.gz upgrades are intentionally removed. The standalone Git upgrader always fetches the pinned `git@github.com:bugz8unny69/anime-discovery.git` over SSH on `develop`. Git is run as root, so **root's effective SSH identity must authenticate**; use `sudo -H`, and do not assume the `anime-discovery` service account's key can be used by root. A one-time test is `sudo -H git ls-remote git@github.com:bugz8unny69/anime-discovery.git HEAD`.

Before activating new code, it records the old and requested Git SHAs to `/var/lib/anime-discovery/upgrade-state.json` and makes an online-safe SQLite backup at the configured path. A successful service health check writes the new healthy SHA atomically. The bootstrapper fetches the new upgrader source from verified fast-forward Git history and executes that copy; it replaces its installed executable **only after success**. Application and Git checkout ownership are reconciled to the existing checkout owner without following symlinks. Do not use a blank/default Git SSH identity if root's key is not configured.

If an interrupted run leaves the checkout exactly at either the recorded old or target SHA **and clean**, the next run first restores the old revision and attempts to restart the service. A dirty or unexpected checkout is **not automatically reset**: it stops and requires review so that unexplained changes are not deleted. This is conservative rerun safety, not a guarantee of automatic recovery from arbitrary filesystem corruption. A failure during an application update may require inspecting the SQLite schema and service logs; code rollback never automatically replaces the live database. This is a Git-only enhancement; no Docker and no automatic release packaging.

## Anime trial lifecycle — authoritative meaning of Keep

**Do not conflate audio validation, trial staging, and the user's Keep button.** This distinction has been lost in previous chats and must be preserved in all future implementation, status labels, and PRs.

1. Autobrr/release-group candidates are identified and acquired under an episode-level duplicate guard. Downloaded files are examined using **actual ffprobe evidence** for both Japanese and English audio; the release title's `Dual-Audio` string is not proof.
2. A candidate that **passes** dual-audio validation is staged into the **anime trial folder served by Jellyfin**, where the user can watch it. **Staging is NOT Keep**, and staging must not import the anime into Sonarr.
3. **Keep is a later, explicit decision by the user after watching the trial in Jellyfin.** Only then does the established downstream workflow send the anime to Sonarr and continue its normal completion/integration steps. Never automatically press Keep or equate download completion/audio pass with this decision.
4. If a candidate **fails Japanese+English audio validation**, it must never enter the Jellyfin trial or Sonarr. The desired workflow is to use the **existing verified, ownership-aware qBittorrent cleanup code** to remove that candidate's torrent **and its torrent payload files**, then safely release its episode claim and try **one** alternate release-group candidate. Deleting a failed candidate's owned torrent payload is distinct from deleting verified staged trial media or Sonarr/library files.
5. Once a valid dual-audio candidate is **successfully staged for trial**, other release-group candidates for that TVDB series/season/episode should be skipped/closed; **do not wait for the user to click Keep** before clearing duplicate waiting jobs. Conversely, an audio failure can promote the next held group **only after cleanup is confirmed**; uncertain ownership, incomplete cleanup, or ambiguous failure must stop for review. Never download all competing groups simultaneously.
6. All runtime torrent deletion must remain restricted to the existing verified ownership/cleanup gates and explicit authorized application policy. **No direct or unconditional qBittorrent deletion, NFS path deletion, or media cleanup** as a shortcut. User permission to implement this behavior in a PR is not permission to run cleanup on live torrents during development.

**Status semantics:** `ON HOLD` means another candidate owns the episode's active trial acquisition; `SKIPPED DUPLICATE` means a valid candidate has been **staged for Jellyfin trial**, not kept in Sonarr; `NEEDS REVIEW` applies to unsafe/uncertain states. These lifecycle statuses are target behavior and must not be claimed implemented by a PR unless code/tests explicitly provide them.

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
4. Keep requested work narrow. Git SSH via standalone upgrader is the chosen upgrade method; remove legacy archive inputs. Future internet-hosted archive support is only a documented possibility.
5. Report separately: coded, PR-open, CI-verified, merged, and deployed. Never conflate them.

**Supporting project notes** (uploaded in conversation; not necessarily in repository): `anime-discovery-pr-handoff-2026-10-21.md`, `gemini-code-1792038645145.md`, `homelab-network-topology.md`, and `server-nas-network-build.md`. Check up-to-date runtime settings against historical notes.

## Recent development handoff — identification and CI efficiency (2026-10-21)

**Check GitHub for current state before acting.** The user merged PRs #75, #76, #77, #78, and #79 into `develop` as observed via GitHub; merging is **not** evidence of deployment to the VM. Do not touch production, media, SQLite, torrents, services or Shoko without explicit approval.

- **PR #75 — AniDB candidate evidence:** New identity evidence retains AniDB IDs, matched titles and alternate titles for readable Matching Details; older ID-only records cannot be retroactively enriched.
- **PR #76 — fail-closed season agreement:** No fabricated TVDB Season 1 or assumed destination episode when Anime-Lists lacks a unique mapping. Such cases remain `NEEDS_REVIEW` with `SEASON_EPISODE_MAPPING_UNVERIFIED`; explicit season disagreement remains a distinct review reason.
- **PR #77 — identity retry UI:** The `Retry identification` button lives **inside Matching Details**, not in the compact Jobs table. It calls the existing CSRF-protected `/api/recheck-identity`, requeues eligible `NEEDS_REVIEW` notifications to `IDENTIFYING`, closes the modal on success and refreshes Jobs. This is not acquisition-job `Retry Now`, does not skip verification, and never overrides provider cooldown.
- **PR #78 — TVDB throttle:** Scoped identity-worker TVDB calls use a shared SQLite request reservation, nominal 1-second spacing, HTTP 429 `Retry-After`, and transient-failure exponential backoff (10 to 600 seconds). Throttle deferrals are `LOOKUP_RETRY` and do not use up identity attempts. This is independent of AniDB's shared 10-second normal request gap and 600-second error backoff. **TVDB token caching and metadata caching were not implemented in PR #78**; do not claim otherwise.
- **PR #79 — CI efficiency:** Stops full-suite runs on every `feature/**` or `fix/**` push, retains PR-to-`develop` and post-merge `develop` tests, keeps manual dispatch, and cancels superseded runs in their event-specific concurrency group.

### Next priority: season-aware, exact episode identification

Re:ZERO notification #19, release `[ToonsHub] ReZERO -Starting Life in Another World- S04E19 ...`, correctly parsed **release Season 4 Episode 19**, but earlier selected TVDB #305089 ↔ AniDB #11370 and reported mapped Season 1. The title check was 100%; series-title identity is **not** season-specific identity. The previous Season 1 fallback was one cause of potentially misleading evidence, now removed by #76. Investigate whether season-specific AniDB candidates are being overlooked, which Anime-Lists rules resolve the release episode, and whether the correct AniDB record is chosen. The public Anime-Lists records previously examined suggested another AniDB entry for Re:ZERO's fourth TVDB season (candidate #19242); **reverify against the actual XML fixture/validated source** rather than treating that as production-cache evidence. Earlier Saga of Tanya the Evil case similarly had release Season 2 versus mapped Season 1.

**Non-negotiable verification:** correct TVDB series ID, verified TVDB season and episode, correct season-specific AniDB anime ID, Anime-Lists episode relationship (including offsets/explicit rules), and **exact internal AniDB episode database ID** from a verified catalog or reviewed mapping. AniDB episode *number* is not an internal episode *ID*. Never auto-approve on title similarity alone; absent or ambiguous evidence means review, while provider cooldown/unavailability means safe retry. Persist provenance for later Shoko integration. Keep Shoko, torrents and acquisition behavior unchanged until explicitly authorized.

### CI / GitHub workflow rules for future assistants

1. Read `.github/workflows/anime-python-tests.yml` at the active `develop` ref before asserting which triggers or concurrency settings apply. Never assume an older handoff is current.
2. Avoid unnecessary per-file feature commits. Where supported, **batch related changes into a single commit**, then open the PR. If the GitHub connector requires sequential per-file commits, minimize avoidable churn. Once PR is open, new commits trigger its checks; obsolete runs should be canceled by concurrency configuration.
3. Use a feature branch based on `develop`, open a PR targeting `develop`, and check **that PR's actual required checks** and final conclusions. Distinguish `push`, `pull_request`, and post-merge `develop` runs. Do not mistake one successful event for another successful event.
4. **Do not ask for merge based only on a green push run.** Confirm relevant PR checks have completed successfully, including run status and conclusion; GitHub UI may display stale/in-progress checks. Never merge without the user's express approval.
5. Treat GitHub Actions usage as a resource: queued time and runner execution differ; refer to Actions billable usage to verify costs. A test suite finishing does not prove the workflow job completed. Investigate stalls and redundant workflow triggers rather than repeatedly suggesting long waits.
6. Every handoff should explicitly state **implemented / CI passed / merged / deployed** as separate states. Updating `develop` by PR does not update a live installation.

### Active next steps

- Prioritize the season-aware candidate discovery and complete AniDB↔TVDB episode-level verification using offline Anime-Lists/AniDB fixtures and tests, keeping fail-closed behavior.
- Evaluate optional TVDB token and metadata caching separately, with credential and freshness safeguards. Do not conflate this with the already merged throttle.
- Do not expand the Jobs table for retry controls; identity retry belongs in Matching Details.
