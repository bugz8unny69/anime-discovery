"""Versioned, atomic configuration snapshots for asynchronous workers.

Admin writes settings.json atomically; daemon reloads between job claims.
Invalid edits preserve the last known-good snapshot.
"""
import asyncio
from dataclasses import dataclass
from anime_flat_config import load_config

@dataclass(frozen=True)
class ConfigSnapshot:
    version: int
    settings: dict
    secrets: dict

class ConfigManager:
    def __init__(self, directory):
        self.directory=directory
        self._snapshot=None
        self._lock=asyncio.Lock()

    @property
    def snapshot(self):
        if self._snapshot is None:
            raise RuntimeError("Configuration not loaded")
        return self._snapshot

    async def reload(self):
        async with self._lock:
            loaded=await asyncio.to_thread(load_config,self.directory)
            current=self._snapshot
            candidate=ConfigSnapshot(
                version=1 if current is None else current.version+1,
                settings=loaded["settings"],secrets=loaded["secrets"])
            self._snapshot=candidate
            return candidate

    async def reload_if_changed(self):
        # Admin can trigger this on every new claim; unchanged settings do not
        # invalidate the snapshot or increment its version.
        loaded=await asyncio.to_thread(load_config,self.directory)
        current=self._snapshot
        if current and current.settings==loaded["settings"] and current.secrets==loaded["secrets"]:
            return current
        return await self.reload()
