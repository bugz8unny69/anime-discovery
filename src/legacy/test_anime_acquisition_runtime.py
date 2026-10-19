import unittest
from anime_acquisition_runtime import acquisition_handlers

class RuntimeTests(unittest.TestCase):
    def test_disabled_by_default(self):
        with self.assertRaises(PermissionError):
            acquisition_handlers("unused.db",lambda:None,
                download_root="/unused",trial_root="/unused")
    def test_explicit_registry_contains_acquisition(self):
        handlers=acquisition_handlers("unused.db",lambda:None,
            download_root="/unused",trial_root="/unused",enabled=True)
        self.assertIn("claimed_acquisition",handlers)
        self.assertTrue(callable(handlers["claimed_acquisition"]))

if __name__=="__main__":
    unittest.main()
