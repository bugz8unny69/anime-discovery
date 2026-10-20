"""Wait for updated settings without running remote monitor checks excessively.

Monitor loops still do their usual check every 60 seconds, but a local atomic
settings/secrets replacement wakes their next iteration within about a second.
No in-process signals or privileged service-manager operations are needed.
"""
import time
from pathlib import Path

from anime_flat_config import DEFAULT_CONFIG_DIR


def signature(directory=DEFAULT_CONFIG_DIR):
    def stamp(path):
        try:
            stat=path.stat()
            return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns)
        except FileNotFoundError:
            return None
    directory=Path(directory)
    return (stamp(directory/"settings.json"),stamp(directory/"secrets.json"))


def wait_for_change(seconds=60, *, directory=DEFAULT_CONFIG_DIR,
                    interval=1, clock=time.monotonic, sleep=time.sleep):
    """True if config changed, False if regular monitor poll is due."""
    if seconds<=0 or interval<=0:
        raise ValueError("Invalid config wait duration")
    baseline=signature(directory)
    deadline=clock()+seconds
    while True:
        left=deadline-clock()
        if left<=0:
            return False
        sleep(min(interval,left))
        if signature(directory)!=baseline:
            return True
