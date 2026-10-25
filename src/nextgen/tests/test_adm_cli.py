"""ADM supports both documented and flag-style password commands."""
import contextlib
import io
import json
import unittest
from unittest.mock import patch

from src.nextgen.api import adm


class FakeSocket:
    def __init__(self):
        self.sent = b""
        self.address = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def settimeout(self, timeout):
        pass

    def connect(self, address):
        self.address = address

    def sendall(self, data):
        self.sent += data

    def recv(self, size):
        return b'{"ok":true}\n'


class AdmCommandTests(unittest.TestCase):
    def execute(self, *argv):
        sock = FakeSocket()
        output = io.StringIO()
        with (patch("sys.argv", ["adm", *argv]),
              patch("src.nextgen.api.adm.socket.socket", return_value=sock),
              patch("src.nextgen.api.adm.getpass.getpass",
                    side_effect=["correct horse battery staple"] * 2),
              contextlib.redirect_stdout(output)):
            adm.main()
        self.assertEqual(sock.address, "/run/anime-discovery/admin.sock")
        self.assertEqual(json.loads(sock.sent), {
            "command": "set-password",
            "password": "correct horse battery staple",
        })
        self.assertIn("password updated", output.getvalue().lower())

    def test_documented_subcommand(self):
        self.execute("set-password")

    def test_flag_alias(self):
        self.execute("--set-password")

    def test_no_command_rejected(self):
        with patch("sys.argv", ["adm"]), self.assertRaises(SystemExit) as raised:
            adm.main()
        self.assertEqual(raised.exception.code, 2)

    def test_conflicting_commands_rejected(self):
        with (patch("sys.argv", ["adm", "set-password", "--set-password"]),
              self.assertRaises(SystemExit) as raised):
            adm.main()
        self.assertEqual(raised.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
