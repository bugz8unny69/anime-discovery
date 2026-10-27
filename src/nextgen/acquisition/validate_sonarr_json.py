"""Inspect a saved Sonarr v4 interactive-release response without network or downloads.

Example:
 python -m src.nextgen.acquisition.validate_sonarr_json \\
    /tmp/sonarr-releases.json --sonarr-series 126 --sonarr-episode 2504 \\
    --tvdb-series 389597 --tvdb-episode 7979142 --season 1 --number 1

JSON files can contain private tracker URLs: never publish the file or raw output.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys

from src.nextgen.acquisition.sonarr_search import DiscoveryPolicy, SearchReview, _release
from src.nextgen.sonarr_episode import VerifiedEpisode


def summarize(rows, identity, *, sonarr_series, sonarr_episode, policy):
    if type(rows) is not list:
        raise ValueError("Expected an array of Sonarr releases.")
    if len(rows) > 1000:
        raise ValueError("Sonarr result exceeds the bounded release limit.")
    releases = tuple(_release(row, sonarr_series, sonarr_episode, identity) for row in rows)
    ranked = policy.rank(releases)
    return {
        "total": len(releases),
        "scope": dict(Counter(row.scope for row in releases)),
        "magnet_sources": sum(row.magnet_url is not None for row in releases),
        "exact_with_magnet": sum(row.scope == "exact" and row.magnet_url is not None
                                 for row in releases),
        "sonarr_approved": sum(row.approved for row in releases),
        "local_eligible": sum(policy.accepts(row) for row in releases),
        "eligible_by_resolution": dict(sorted(Counter(
            row.resolution for row in releases if policy.accepts(row)).items())),
        "top_eligible": [
            {"resolution": row.resolution, "seeders": row.seeders,
             "indexer": row.indexer[:128], "sonarr_approved": row.approved}
            for row in ranked if policy.accepts(row)
        ][:10],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("json_file", type=Path)
    parser.add_argument("--sonarr-series", type=int, required=True)
    parser.add_argument("--sonarr-episode", type=int, required=True)
    parser.add_argument("--tvdb-series", type=int, required=True)
    parser.add_argument("--tvdb-episode", type=int, required=True)
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--number", type=int, required=True)
    parser.add_argument("--max-resolution", type=int, choices=(720, 1080, 2160), default=1080)
    parser.add_argument("--min-seeders", type=int, default=5)
    parser.add_argument("--rank-by", choices=("resolution", "seeders"), default="resolution")
    args = parser.parse_args(argv)

    try:
        identity = VerifiedEpisode(args.tvdb_series, args.tvdb_episode,
                                   args.season, args.number)
        policy = DiscoveryPolicy(args.max_resolution, args.min_seeders, args.rank_by)
        if args.sonarr_series <= 0 or args.sonarr_episode <= 0:
            raise ValueError("Sonarr IDs must be positive.")
        if args.json_file.stat().st_size > 4 * 1024 * 1024:
            raise ValueError("Release JSON exceeds 4 MiB.")
        rows = json.loads(args.json_file.read_text(encoding="utf-8"))
        result = summarize(rows, identity, sonarr_series=args.sonarr_series,
                           sonarr_episode=args.sonarr_episode, policy=policy)
    except (OSError, ValueError, TypeError, SearchReview) as exc:
        # Never echo provider URLs, credentials, or untrusted fields in an exception.
        print("Invalid file, identity or release data; no acquisition attempted.",
              file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
