"""Offline tests for the independent Git upgrade bootstrapper; no live services."""
import importlib.util
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "anime-discovery-upgrade.py"
spec = importlib.util.spec_from_file_location("standalone_ad_upgrade", SCRIPT)
upgrade = importlib.util.module_from_spec(spec)
spec.loader.exec_module(upgrade)

OLD = "a" * 40
NEW = "b" * 40


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.base = Path(temp.name)
        self.root = self.base / "checkout"
        self.root.mkdir()
        (self.root / ".git").mkdir()
        self.state = self.base / "upgrade-state.json"
        self.config = self.base / "config"
        self.config.mkdir()
        self.db = self.base / "data.sqlite"
        with sqlite3.connect(self.db) as db:
            db.execute("CREATE TABLE schema_version(version INTEGER)")
            db.execute("INSERT INTO schema_version VALUES (1)")
        (self.config / "settings.json").write_text(
            json.dumps({"daemon": {"database_path": str(self.db)}}))

    def test_state_written_atomically_and_file_restricted(self):
        upgrade.save_state(self.state, {"healthy": OLD})
        self.assertEqual(upgrade.read_state(self.state), {"healthy": OLD})
        self.assertEqual(self.state.stat().st_mode & 0o777, 0o600)

    def test_rejects_untrusted_state_hash(self):
        self.state.write_text('{"pending_from": "not-a-sha"}')
        with self.assertRaisesRegex(ValueError, "Invalid stored commit"):
            upgrade.read_state(self.state)

    def test_noop_records_healthy_revision(self):
        def fake_git(root, *args):
            mapping = {
                ("rev-parse", "HEAD"): OLD,
                ("status", "--porcelain"): "",
                ("rev-parse", "FETCH_HEAD"): OLD,
                ("merge-base", OLD, OLD): OLD
            }
            return mapping[args]
        with patch.object(upgrade, "git", side_effect=fake_git), patch.object(
                upgrade, "ownership") as own:
            result = upgrade.apply(self.root, self.state, self.config, "fake.service", OLD)
        self.assertFalse(result["updated"])
        self.assertEqual(upgrade.read_state(self.state)["healthy"], OLD)
        own.assert_called_once()

    def test_interrupted_upgrade_reverts_only_known_target(self):
        upgrade.save_state(self.state, {"healthy": OLD,
                    "pending_from": OLD, "pending_to": NEW})
        actions = []
        def fake_git(root, *args):
            actions.append(("git",) + args)
            if args == ("rev-parse", "HEAD"):
                return NEW
            if args == ("status", "--porcelain"):
                return ""
            if args == ("reset", "--hard", OLD):
                return ""
            raise AssertionError(args)
        with patch.object(upgrade, "git", side_effect=fake_git), patch.object(
                upgrade, "call", side_effect=lambda *args: actions.append(args)), patch.object(
                upgrade, "ready"), patch.object(upgrade, "ownership"):
            result = upgrade.recover(self.root, self.state, "fake.service", 1000, 1000)
        self.assertEqual(result, {"healthy": OLD})
        self.assertIn(("git", "reset", "--hard", OLD), actions)
        self.assertLess(actions.index(("systemctl", "stop", "fake.service")),
                        actions.index(("git", "reset", "--hard", OLD)))

    def test_dirty_interruption_never_resets_or_stops_service(self):
        upgrade.save_state(self.state, {"healthy": OLD,
                    "pending_from": OLD, "pending_to": NEW})
        def fake_git(root, *args):
            return NEW if args == ("rev-parse", "HEAD") else " M local.txt"
        with patch.object(upgrade, "git", side_effect=fake_git), patch.object(
                upgrade, "call") as cmd:
            with self.assertRaisesRegex(RuntimeError, "dirty"):
                upgrade.recover(self.root, self.state, "fake.service", 1000, 1000)
        cmd.assert_not_called()

    def test_unknown_head_requires_manual_review(self):
        upgrade.save_state(self.state, {"healthy": OLD,
                    "pending_from": OLD, "pending_to": NEW})
        with patch.object(upgrade, "git", return_value="c" * 40), patch.object(
                upgrade, "call") as cmd:
            with self.assertRaisesRegex(RuntimeError, "unknown HEAD"):
                upgrade.recover(self.root, self.state, "fake.service", 1000, 1000)
        cmd.assert_not_called()

    def test_db_validation_without_importing_runtime(self):
        self.assertEqual(upgrade.verify_db(self.config), self.db)
        backup = upgrade.backup_db(self.db, OLD)
        with sqlite3.connect(backup) as db:
            self.assertEqual(db.execute("SELECT version FROM schema_version").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
