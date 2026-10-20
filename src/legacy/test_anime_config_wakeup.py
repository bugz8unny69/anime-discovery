import tempfile
import unittest
from pathlib import Path

from anime_config_wakeup import wait_for_change


class ConfigurationWakeupTests(unittest.TestCase):
    def test_atomic_setting_replacement_wakes_monitor_without_full_poll(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            settings=folder/"settings.json"
            settings.write_text("{}")
            (folder/"secrets.json").write_text("{}")
            instant=[0]
            def sleep(seconds):
                instant[0]+=seconds
                settings.replace(folder/"old.json")
                (folder/"settings.json").write_text('{"anidb":{"client":"registeredclient"}}')
            self.assertTrue(wait_for_change(60,directory=folder,interval=1,
                                            clock=lambda:instant[0],sleep=sleep))
            self.assertEqual(instant[0],1)

    def test_no_change_waits_until_regular_poll(self):
        with tempfile.TemporaryDirectory() as temp:
            folder=Path(temp)
            (folder/"settings.json").write_text("{}")
            (folder/"secrets.json").write_text("{}")
            now=[0]
            def sleep(seconds):
                now[0]+=seconds
            self.assertFalse(wait_for_change(3,directory=folder,clock=lambda:now[0],
                                             sleep=sleep))
            self.assertEqual(now[0],3)


if __name__=="__main__":
    unittest.main()
