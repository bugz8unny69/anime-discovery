"""Anime Discovery worker; all runtime options come from flat configuration."""
import asyncio
from pathlib import Path
from anime_flat_config import load_config
from anime_acquisition_runtime import acquisition_handlers
from anime_async_daemon import run_workers
from anime_qb_api import QBittorrentAPI
from anime_prowlarr_search import ProwlarrClient
from anime_shared_discovery import handler_factory


def main():
    config = load_config()
    settings, secrets = config["settings"], config["secrets"]
    daemon, qb, storage = settings["daemon"], settings["qbittorrent"], settings["storage"]
    db_path = Path(daemon["database_path"])
    download_root, trial_root = Path(storage["download_root"]), Path(storage["trial_root"])
    if not db_path.is_file():
        raise RuntimeError("Database missing: " + str(db_path))
    if not storage["download_root"] or not storage["trial_root"] or not download_root.is_dir() or not trial_root.is_dir():
        raise RuntimeError("Configure existing storage.download_root and storage.trial_root")
    if not qb["username"] or not secrets.get("qbittorrent_password"):
        raise RuntimeError("Configure qbittorrent.username and secrets.json qbittorrent_password")

    def qb_factory():
        client = QBittorrentAPI(qb["base_url"], allow_writes=True)
        client.login(qb["username"], secrets["qbittorrent_password"])
        return client

    handlers = acquisition_handlers(
        db_path, qb_factory, download_root=download_root,
        trial_root=trial_root, enabled=True, cleanup_source=qb["cleanup_source"])
    if settings["prowlarr"]["enabled"]:
        def prowlarr_factory():
            return ProwlarrClient(settings["prowlarr"]["base_url"],
                                  secrets["prowlarr_api_key"])
        handlers["series_gap_search"]=handler_factory(db_path,prowlarr_factory)
    print("Anime Discovery worker running", flush=True)
    try:
        asyncio.run(run_workers(db_path, handlers, concurrency=daemon["concurrency"]))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
