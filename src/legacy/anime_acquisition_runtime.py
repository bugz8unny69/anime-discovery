"""Explicit, non-default acquisition handler registry.

The production daemon entrypoint continues to register SAFE_HANDLERS only.
Creating this registry does not start workers or contact external services.
"""
from anime_safe_handlers import SAFE_HANDLERS
from anime_acquisition_handler import make_acquisition_handler

def acquisition_handlers(db_path, qb_factory, *, download_root, trial_root,
                         enabled=False, cleanup_source=False, jellyfin_refresh=None, staged_directory_mode="2770", staged_file_mode="0640"):
    if enabled is not True:
        raise PermissionError("Acquisition handlers require explicit opt-in")
    handlers=dict(SAFE_HANDLERS)
    handlers["claimed_acquisition"]=make_acquisition_handler(
        db_path,qb_factory,download_root=download_root,trial_root=trial_root, cleanup_source=cleanup_source, jellyfin_refresh=jellyfin_refresh,
            staged_directory_mode=staged_directory_mode,staged_file_mode=staged_file_mode)
    return handlers
