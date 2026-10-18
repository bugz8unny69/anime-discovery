import asyncio
import json
import os
import tempfile
import unittest
from pathlib import Path
from anime_config_reload import ConfigManager

class ReloadTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path=Path(self.temp.name)
        self.settings=self.path/"settings.json"
        self.settings.write_text('{"daemon":{"concurrency":2}}')
        secret=self.path/"secrets.json"
        secret.write_text("{}")
        os.chmod(secret,0o600)
        self.manager=ConfigManager(self.path)

    async def test_snapshot_version_and_last_good(self):
        original=await self.manager.reload()
        self.assertEqual(original.settings["daemon"]["concurrency"],2)
        self.assertIs(await self.manager.reload_if_changed(),original)
        self.settings.write_text('{"daemon":{"concurrency":3}}')
        changed=await self.manager.reload_if_changed()
        self.assertEqual(changed.version,2)
        self.assertEqual(changed.settings["daemon"]["concurrency"],3)
        self.settings.write_text("{invalid")
        with self.assertRaises(json.JSONDecodeError):
            await self.manager.reload_if_changed()
        self.assertIs(self.manager.snapshot,changed)

if __name__=="__main__":
    unittest.main()
