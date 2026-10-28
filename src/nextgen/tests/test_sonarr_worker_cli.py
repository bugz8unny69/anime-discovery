"""The installed worker command must actually expose opted-in Sonarr acquisition."""
import unittest
from unittest.mock import patch

from src.nextgen.__main__ import main


class SonarrWorkerCliTests(unittest.TestCase):
    def test_sonarr_acquire_enables_existing_worker_pipeline(self):
        calls = []

        async def serve(config_dir, **options):
            calls.append((config_dir, options))

        with patch('src.nextgen.__main__.check_local'), patch(
            'src.nextgen.providers.configuration.run_identity_worker', new=serve
        ):
            self.assertEqual(main(['worker', '--config-dir', '/test/config',
                                   '--sonarr-acquire']), 0)

        self.assertEqual(calls, [('/test/config', {
            'sonarr_backfill': True,
            'sonarr_select': True,
            'sonarr_acquire': True,
        })])

    def test_default_worker_keeps_sonarr_opt_in(self):
        calls = []

        async def serve(config_dir, **options):
            calls.append(options)

        with patch('src.nextgen.__main__.check_local'), patch(
            'src.nextgen.providers.configuration.run_identity_worker', new=serve
        ):
            self.assertEqual(main(['worker', '--config-dir', '/test/config']), 0)

        self.assertEqual(calls, [{
            'sonarr_backfill': False,
            'sonarr_select': False,
            'sonarr_acquire': False,
        }])
