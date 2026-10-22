# Backfill design — deferred work (no implementation)

Automatic Prowlarr backfill is explicitly **out of scope for PR #89**. The decision to make backfill automatic, manual, or approval-based is not settled.

## Questions to resolve before writing code
- Should incoming verified but out-of-range episodes automatically request missing evaluation episodes, or should the dashboard offer a user-initiated search?
- What event should trigger backfill, and how frequently may it run?
- How do verified series titles, season boundaries, available indexers and Prowlarr selection work without relying on the torrent filename?
- How do duplicate requests, failed queries, partial availability, competing release groups, limits, cleanup and retries work safely?
- What should the dashboard show for skipped incoming episodes and individual acquisition outcomes?

## Future implementation tasks
- Independently test the existing `anime_shared_discovery.py` and `anime_prowlarr_search.py` code for the chosen behavior.
- Use the completed job orchestrator's independent-job handoff API if a search job is needed.
- Preserve independently verified TVDB/AniDB identity, Japanese+English audio verification, size rules, torrent ownership and cleanup, evaluation staging, and explicit Keep.
- Add offline integration tests before enabling any automatic downloads.

This PR is a placeholder for design discussion only, not authorization to enable automatic backfill, merge, or deploy.
