"""Offline behavioral checks for setting propagation without a service restart."""
import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from anime_flat_config import DEFAULT_SETTINGS


def load_script(name,path):
    spec=importlib.util.spec_from_file_location(name,Path(__file__).with_name(path))
    module=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LiveWorkerSettingsTests(unittest.IsolatedAsyncioTestCase):
    async def test_acquisition_and_prowlarr_use_fresh_snapshot_per_job(self):
        module=load_script("worker_hot_settings_test","anime-discovery-worker.py")
        from copy import deepcopy
        initial=deepcopy(DEFAULT_SETTINGS)
        initial["daemon"]["database_path"]="/tmp/example.db"
        initial["storage"]={"download_root":"/tmp/download","trial_root":"/tmp/trial"}
        initial["qbittorrent"]["username"]="user"
        secrets={"qbittorrent_password":"old"}
        seen=[]
        class FakeQb:
            def __init__(self,url,*,allow_writes):
                self.url=url
            def login(self,username,password):
                seen.append(("qb",self.url,username,password))
        def fake_acquisition(path,qb_factory,**kw):
            async def acquisition(job):
                qb_factory()
                seen.append(("jellyfin",bool(kw.get("jellyfin_refresh"))))
                seen.append(("cleanup",kw.get("cleanup_source")))
                return "DONE"
            return {"claimed_acquisition":acquisition}
        class FakeProwlarr:
            def __init__(self,url,key):
                seen.append(("prowlarr",url,key))
        def fake_gap(path,client_factory):
            async def process(job):
                client_factory()
                return "DONE"
            return process
        with (patch.object(module,"acquisition_handlers",side_effect=fake_acquisition),
              patch.object(module,"QBittorrentAPI",FakeQb),
              patch.object(module,"ProwlarrClient",FakeProwlarr),
              patch.object(module,"handler_factory",side_effect=fake_gap)):
            handlers=module.runtime_handlers(Path("/tmp/example.db"),
                {"settings":initial,"secrets":secrets})
            self.assertEqual(await handlers["series_gap_search"]({
                "config_snapshot":SimpleNamespace(settings=initial,secrets=secrets)}),"DEFERRED")
            updated=deepcopy(initial)
            updated["jellyfin"]["enabled"]=True
            updated["jellyfin"]["base_url"]="https://jellyfin.lab"
            updated["prowlarr"]["enabled"]=True
            updated["prowlarr"]["base_url"]="http://prowlarr.lab"
            updated["qbittorrent"]["base_url"]="http://qb-new.lab"
            updated["qbittorrent"]["cleanup_source"]=False
            new_secrets={**secrets,"qbittorrent_password":"rotated","prowlarr_api_key":"newkey"}
            job={"config_snapshot":SimpleNamespace(settings=updated,secrets=new_secrets)}
            self.assertEqual(await handlers["claimed_acquisition"](job),"DONE")
            self.assertEqual(await handlers["series_gap_search"](job),"DONE")
        self.assertIn(("qb","http://qb-new.lab","user","rotated"),seen)
        self.assertIn(("jellyfin",True),seen)
        self.assertIn(("cleanup",False),seen)
        self.assertIn(("prowlarr","http://prowlarr.lab","newkey"),seen)


class LiveLauncherSettingsTests(unittest.TestCase):
    def test_disabled_monitors_are_still_launched_as_idle_processes(self):
        module=load_script("launcher_hot_settings_test","anime-discovery-live.py")
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/"database.db"
            path.touch()
            settings={"daemon":{"database_path":str(path)},
                      "web":{"host":"127.0.0.1","port":8765},
                      "sonarr":{"enabled":False},
                      "shoko":{"enabled":False}}
            process=[]
            class FakeChild:
                def __init__(self,args):
                    self.args=args
                    self.terminated=False
                    process.append(self)
                def poll(self):
                    return None if not self.terminated else 0
                def terminate(self):
                    self.terminated=True
                def wait(self,timeout=None):
                    return 0
            with (patch.object(module,"load_config",return_value={"settings":settings}),
                  patch.object(module.subprocess,"Popen",side_effect=FakeChild),
                  patch.object(module.time,"sleep",side_effect=KeyboardInterrupt)):
                module.main()
            names=[p.args[-1].name for p in process]
            self.assertIn("anime_sonarr_import_monitor.py",names)
            self.assertIn("anime_shoko_handoff_monitor.py",names)
            self.assertTrue(all(p.terminated for p in process))


if __name__=="__main__":
    unittest.main()
