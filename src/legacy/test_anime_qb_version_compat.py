"""Offline qBittorrent 4.5.2 / 5.x Web API compatibility contracts.

No real qBittorrent connection and no live torrent writes.
"""
import json
import unittest
from urllib.parse import parse_qs

from anime_qb_api import QBittorrentAPI

HASH = "a" * 40
MARKER = "ad-" + "b" * 32


class Response:
    status = 200

    def __init__(self, data):
        self.data = data

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.data


class FakeQb:
    def __init__(self, webapi, *, owned=True, initial_priorities=None):
        self.webapi = webapi
        try:
            parts = tuple(map(int, webapi.split(".")))
        except ValueError:
            parts = (0, 0, 0)
        self.new = parts >= (2, 11, 0)
        self.state = "stoppedDL" if self.new else "pausedDL"
        self.owned = owned
        self.priority = initial_priorities or {0: 1, 1: 1, 2: 1}
        self.requests = []
        self.add_fields = None

    def open(self, request, timeout=None):
        url = request.full_url
        fields = parse_qs(request.data.decode()) if request.data else {}
        self.requests.append((url, fields))
        if url.endswith("/app/webapiVersion"):
            return Response(self.webapi.encode())
        if "/torrents/info?" in url:
            row = {"hash": HASH, "state": self.state,
                   "category": "anime-discovery" if self.owned else "other",
                   "tags": MARKER if self.owned else ""}
            return Response(json.dumps([row]).encode())
        if "/torrents/files?" in url:
            return Response(json.dumps([
                {"index": i, "name": "Anime S01E%02d.mkv" % (i + 1),
                 "priority": priority} for i, priority in self.priority.items()
            ]).encode())
        if url.endswith("/torrents/categories"):
            return Response(b'{"anime-discovery":{}}')
        if url.endswith("/torrents/add"):
            self.add_fields = fields
            return Response(b"Ok.")
        if url.endswith("/torrents/filePrio"):
            for index in fields["id"][0].split("|"):
                self.priority[int(index)] = int(fields["priority"][0])
            return Response(b"Ok.")
        if url.endswith("/torrents/pause") or url.endswith("/torrents/stop"):
            self.state = "stoppedDL" if self.new else "pausedDL"
            return Response(b"")
        if url.endswith("/torrents/resume") or url.endswith("/torrents/start"):
            self.state = "downloading"
            return Response(b"")
        raise AssertionError("Unexpected endpoint: " + url)


class QbCompatibilityTests(unittest.TestCase):
    def _client(self, webapi, *, owned=True, allow_writes=True, initial_priorities=None):
        fake = FakeQb(webapi, owned=owned, initial_priorities=initial_priorities)
        client = QBittorrentAPI("http://localhost:8080",
                               opener=fake, allow_writes=allow_writes)
        return client, fake

    def test_debian_4_5_2_uses_paused_and_pause_resume(self):
        qb, fake = self._client("2.8.11")
        self.assertEqual(qb.web_api_version(), (2, 8, 11))
        qb.add_magnet("magnet:?xt=urn:btih:" + HASH,
                      category="anime-discovery", tag=MARKER, stopped=True)
        self.assertEqual(fake.add_fields["paused"], ["true"])
        self.assertNotIn("stopped", fake.add_fields)
        self.assertEqual(qb.stop_owned_torrent(HASH), "pausedDL")
        qb.apply_stopped_file_selection(HASH, wanted_indices=[0],
                                         skip_indices=[1, 2])
        self.assertTrue(qb.start_selected_torrent(
            HASH, wanted_indices=[0], skip_indices=[1, 2]))
        names = [url.split("/api/v2/")[1].split("?")[0]
                 for url, _ in fake.requests]
        self.assertIn("torrents/pause", names)
        self.assertIn("torrents/resume", names)
        self.assertNotIn("torrents/start", names)
        self.assertEqual(fake.priority, {0: 1, 1: 0, 2: 0})

    def test_qbittorrent_5_uses_stopped_and_stop_start(self):
        qb, fake = self._client("2.11.0")
        qb.add_magnet("magnet:?xt=urn:btih:" + HASH,
                      category="anime-discovery", tag=MARKER, stopped=True)
        self.assertEqual(fake.add_fields["stopped"], ["true"])
        self.assertNotIn("paused", fake.add_fields)
        self.assertEqual(qb.stop_owned_torrent(HASH), "stoppedDL")
        qb.apply_stopped_file_selection(HASH, wanted_indices=[0],
                                         skip_indices=[1, 2])
        qb.start_selected_torrent(HASH, wanted_indices=[0],
                                  skip_indices=[1, 2])
        names = [url.split("/api/v2/")[1].split("?")[0]
                 for url, _ in fake.requests]
        self.assertIn("torrents/stop", names)
        self.assertIn("torrents/start", names)
        self.assertNotIn("torrents/resume", names)

    def test_resume_requires_every_file_priority_to_match(self):
        qb, fake = self._client("2.8.11")
        with self.assertRaisesRegex(RuntimeError, "priorities differ"):
            qb.start_selected_torrent(HASH, wanted_indices=[0],
                                      skip_indices=[1, 2])
        self.assertFalse(any(url.endswith("/torrents/resume")
                             for url, _ in fake.requests))

    def test_no_start_without_exact_owned_torrent(self):
        qb, fake = self._client("2.8.11", owned=False)
        with self.assertRaises(PermissionError):
            qb.start_selected_torrent(HASH, wanted_indices=[0],
                                      skip_indices=[1, 2])
        self.assertFalse(any(url.endswith("/torrents/resume")
                             for url, _ in fake.requests))

    def test_no_start_while_active_or_with_incomplete_file_selection(self):
        qb, fake = self._client("2.11.0")
        fake.state = "downloading"
        with self.assertRaisesRegex(RuntimeError, "not stopped"):
            qb.start_selected_torrent(HASH, wanted_indices=[0],
                                      skip_indices=[1, 2])
        fake.state = "stoppedDL"
        with self.assertRaisesRegex(RuntimeError, "file list differs"):
            qb.start_selected_torrent(HASH, wanted_indices=[0],
                                      skip_indices=[1])
        self.assertFalse(any(url.endswith("/torrents/start")
                             for url, _ in fake.requests))

    def test_unknown_api_version_fails_closed(self):
        for value in ("2.0", "bad", "3.0.0"):
            qb, fake = self._client(value)
            with self.assertRaises(RuntimeError):
                qb.add_magnet("magnet:?xt=urn:btih:" + HASH,
                              category="anime-discovery", tag=MARKER, stopped=True)
            self.assertFalse(any(url.endswith("/torrents/add")
                                 for url, _ in fake.requests))

    def test_read_only_refuses_start_or_stop(self):
        qb, fake = self._client("2.8.11", allow_writes=False)
        with self.assertRaises(PermissionError):
            qb.stop_owned_torrent(HASH)
        with self.assertRaises(PermissionError):
            qb.start_selected_torrent(HASH, wanted_indices=[0],
                                      skip_indices=[1, 2])
        self.assertEqual(fake.requests, [])


if __name__ == "__main__":
    unittest.main()
