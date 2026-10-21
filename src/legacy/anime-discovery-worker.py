"""Anime Discovery worker; refresh integration settings at each job boundary.

Acquisition jobs already in flight complete using their initial snapshot. New
jobs use the latest valid settings/secrets without restarting the worker or
interrupting in-flight transfers.
"""
import asyncio
import logging
from anime_diagnostics import configure_logging, event
from pathlib import Path

from anime_flat_config import load_config
from anime_config_reload import ConfigManager
from anime_acquisition_runtime import acquisition_handlers
from anime_async_daemon import run_workers
from anime_qb_api import QBittorrentAPI
from anime_prowlarr_search import ProwlarrClient
from anime_shared_discovery import handler_factory
from anime_identity_job import handler_factory as identity_handler_factory
from anime_batch_worker import handler_factory as batch_handler_factory
from anime_jellyfin_refresh import refresh_library


def runtime_handlers(db_path, initial_config):
    """Build a stable registry whose integration handlers use per-job snapshots."""
    initial=initial_config["settings"]
    storage=initial["storage"]
    download_root,trial_root=Path(storage["download_root"]),Path(storage["trial_root"])

    def initial_factory():
        cfg=initial_config
        qb=cfg["settings"]["qbittorrent"]
        client=QBittorrentAPI(qb["base_url"],allow_writes=True)
        client.login(qb["username"],cfg["secrets"]["qbittorrent_password"])
        return client

    handlers=acquisition_handlers(db_path,initial_factory,
        download_root=download_root,trial_root=trial_root,enabled=True,
        cleanup_source=initial["qbittorrent"]["cleanup_source"])

    def configuration(job):
        snapshot=job.get("config_snapshot")
        if snapshot is not None:
            return snapshot.settings,snapshot.secrets
        cfg=load_config()
        return cfg["settings"],cfg["secrets"]

    async def acquire(job):
        settings,secrets=configuration(job)
        # Storage and DB locations are not dashboard-editable. Fail closed if
        # an administrator changes them without restarting infrastructure.
        if (settings["daemon"]["database_path"]!=str(db_path) or
            any(settings["storage"][key]!=storage[key]
                for key in ("download_root","trial_root"))):
            return "BLOCKED"
        qb=settings["qbittorrent"]
        def qb_factory():
            client=QBittorrentAPI(qb["base_url"],allow_writes=True)
            client.login(qb["username"],secrets["qbittorrent_password"])
            return client
        jellyfin_refresh=None
        if settings["jellyfin"]["enabled"]:
            jellyfin_refresh=lambda:refresh_library(
                settings["jellyfin"]["base_url"],secrets["jellyfin_api_key"])
        live=acquisition_handlers(db_path,qb_factory,
            download_root=download_root,trial_root=trial_root,
            enabled=True,cleanup_source=qb["cleanup_source"],
            jellyfin_refresh=jellyfin_refresh,
            staged_owner=settings["storage"].get("staged_owner",""),
            staged_group=settings["storage"].get("staged_group",""),
            staged_directory_mode=settings["storage"].get("staged_directory_mode","2770"),
            staged_file_mode=settings["storage"].get("staged_file_mode","0640"),
            size_settings=settings["trial"],
            sonarr_root=settings.get("sonarr",{}).get("root_folder"))
        return await live["claimed_acquisition"](job)

    async def gap_search(job):
        settings,secrets=configuration(job)
        if not settings["prowlarr"]["enabled"]:
            return "DEFERRED"
        def prowlarr_factory():
            return ProwlarrClient(settings["prowlarr"]["base_url"],
                                  secrets["prowlarr_api_key"])
        return await handler_factory(db_path,prowlarr_factory)(job)

    async def batch(job):
        settings,secrets=configuration(job)
        # Exactly the same immutable infrastructure-root check used by
        # the existing single-episode acquisition handler.
        if (settings["daemon"]["database_path"]!=str(db_path) or
            any(settings["storage"][key]!=storage[key]
                for key in ("download_root","trial_root"))):
            return "BLOCKED"
        qb_settings=settings["qbittorrent"]
        def qb_factory(_job):
            client=QBittorrentAPI(qb_settings["base_url"],allow_writes=True)
            client.login(qb_settings["username"],secrets["qbittorrent_password"])
            return client
        return await batch_handler_factory(db_path,qb_factory,
            download_root=download_root,trial_root=trial_root,
            settings_supplier=lambda _job:settings)(job)

    handlers["identity_resolution"]=identity_handler_factory(db_path,configuration)
    handlers["claimed_acquisition"]=acquire
    handlers["series_gap_search"]=gap_search
    handlers["verified_batch_acquisition"]=batch
    return handlers


def main():
    configure_logging()
    config=load_config()
    settings,secrets=config["settings"],config["secrets"]
    daemon,qb,storage=settings["daemon"],settings["qbittorrent"],settings["storage"]
    db_path=Path(daemon["database_path"])
    download_root,trial_root=Path(storage["download_root"]),Path(storage["trial_root"])
    if not db_path.is_file():
        raise RuntimeError("Database missing: "+str(db_path))
    if (not storage["download_root"] or not storage["trial_root"] or
            not download_root.is_dir() or not trial_root.is_dir()):
        raise RuntimeError("Configure existing storage.download_root and storage.trial_root")
    if not qb["username"] or not secrets.get("qbittorrent_password"):
        raise RuntimeError("Configure qbittorrent.username and secrets.json qbittorrent_password")
    handlers=runtime_handlers(db_path,config)
    print("Anime Discovery worker running; integration settings reload per job",flush=True)
    try:
        asyncio.run(run_workers(db_path,handlers,concurrency=daemon["concurrency"],
                                config_manager=ConfigManager("/etc/anime-discovery")))
    except KeyboardInterrupt:
        pass


if __name__=="__main__":
    main()
