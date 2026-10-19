"""Runnable Anime Discovery acquisition worker.

Run only when ready to process queued, approved acquisitions. This is an
application entrypoint, not an installer or a systemd service.
"""
import argparse
import asyncio
import os
from pathlib import Path

from anime_acquisition_runtime import acquisition_handlers
from anime_async_daemon import run_workers
from anime_qb_api import QBittorrentAPI


def main(argv=None):
    parser = argparse.ArgumentParser(description="Anime Discovery acquisition worker")
    parser.add_argument("--db", type=Path, default=Path("/var/lib/anime-discovery/anime-discovery.db"))
    parser.add_argument("--download-root", type=Path, required=True)
    parser.add_argument("--trial-root", type=Path, required=True)
    parser.add_argument("--qb-url", required=True)
    parser.add_argument("--qb-user", default=os.environ.get("ANIME_QB_USER"))
    parser.add_argument("--qb-password", default=os.environ.get("ANIME_QB_PASSWORD"))
    parser.add_argument("--concurrency", type=int, default=2)
    args = parser.parse_args(argv)

    if not args.db.is_file():
        parser.error("Database does not exist; run admin new-database first")
    if not args.download_root.is_dir() or not args.trial_root.is_dir():
        parser.error("Download and trial directories must already exist")
    if not args.qb_user or not args.qb_password:
        parser.error("Supply qBittorrent credentials via arguments or environment")

    def qb_factory():
        client = QBittorrentAPI(args.qb_url, allow_writes=True)
        client.login(args.qb_user, args.qb_password)
        return client

    handlers = acquisition_handlers(
        args.db, qb_factory, download_root=args.download_root,
        trial_root=args.trial_root, enabled=True)
    print("Anime Discovery worker running; Ctrl+C to stop", flush=True)
    try:
        asyncio.run(run_workers(args.db, handlers, concurrency=args.concurrency))
    except KeyboardInterrupt:
        print("Anime Discovery worker stopped", flush=True)


if __name__ == "__main__":
    main()
