"""Offline, read-only Prowlarr discovery contract tests. No network or CI."""
import io
import json
import unittest
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlsplit

from src.nextgen.acquisition.prowlarr import (
    MAX_RESPONSE, ProwlarrAuthenticationError, ProwlarrClient,
    ProwlarrConfigurationError, ProwlarrCredentials, ProwlarrInvalidResponse,
    ProwlarrOptions, ProwlarrUnavailable, candidates,
)
from src.nextgen.trial_policy import Window

HASH10 = "a" * 40
HASH11 = "b" * 40
HASH12 = "c" * 40


def item(title, digest, *, seeders=12):
    return {
        "title": title, "seeders": seeders,
        "magnetUrl": "magnet:?xt=urn:btih:" + digest + "&dn=example",
    }


class FakeResponse(io.BytesIO):
    status = 200


class ProwlarrClientTests(unittest.TestCase):
    def test_search_uses_api_key_header_bounded_query_and_no_download(self):
        seen = []
        def opener(request, *, timeout):
            seen.append((request, timeout))
            return FakeResponse(json.dumps([item("Shiki - 10", HASH10)]).encode())
        client = ProwlarrClient(ProwlarrOptions("https://prowlarr.example/", 7),
                                ProwlarrCredentials("private-key"), opener=opener)
        self.assertEqual(len(client.search("Shiki & Friends")), 1)
        request, timeout = seen[0]
        parsed = urlsplit(request.full_url)
        self.assertEqual(parsed.path, "/api/v1/search")
        self.assertEqual(parse_qs(parsed.query), {"query": ["Shiki & Friends"], "type": ["search"]})
        self.assertEqual(request.get_header("X-api-key"), "private-key")
        self.assertEqual(timeout, 7)
        self.assertNotIn("private-key", repr(client._credentials))

    def test_configuration_fail_closed(self):
        for bad in ("file:///etc/passwd", "https://user:pass@example.org", "https://example.org/api",
                    "https://example.org/?token=x", "http://host.local/#frag"):
            with self.subTest(bad=bad), self.assertRaises(ProwlarrConfigurationError):
                ProwlarrOptions(bad)
        with self.assertRaises(ProwlarrConfigurationError):
            ProwlarrCredentials("key\n")
        with self.assertRaises(ProwlarrConfigurationError):
            ProwlarrOptions("http://localhost", True)

    def test_auth_and_unavailable_errors_do_not_echo_request(self):
        def unauthorized(request, *, timeout):
            raise HTTPError(request.full_url, 401, "not authorized", {}, None)
        client = ProwlarrClient(ProwlarrOptions("https://prowlarr.example"),
                                ProwlarrCredentials("secret"), opener=unauthorized)
        with self.assertRaises(ProwlarrAuthenticationError) as caught:
            client.search("Shiki")
        self.assertNotIn("secret", str(caught.exception))

        def unavailable(request, *, timeout):
            return type("ErrorResponse", (FakeResponse,), {"status": 503})(b"")
        with self.assertRaises(ProwlarrUnavailable):
            ProwlarrClient(ProwlarrOptions("https://prowlarr.example"),
                           ProwlarrCredentials("secret"), opener=unavailable).search("Shiki")

    def test_invalid_or_oversized_results_are_rejected(self):
        for response in (b'{"results":[]}', b"{broken", b"x" * (MAX_RESPONSE + 1),
                         json.dumps([{}] * 501).encode()):
            with self.subTest(size=len(response)), self.assertRaises(ProwlarrInvalidResponse):
                ProwlarrClient(ProwlarrOptions("https://prowlarr.example"),
                               ProwlarrCredentials("secret"),
                               opener=lambda request, timeout: FakeResponse(response)).search("Shiki")


class CandidateTests(unittest.TestCase):
    def test_verification_scope_and_frozen_window_are_required(self):
        releases = [
            item("[Fansub] Shiki - 01 [1080p]", "d" * 40),
            item("[Fansub] Shiki - 06 [1080p]", "e" * 40),
            item("[Fansub] Shiki S01E10 [1080p]", HASH10),
            item("[Fansub] Shiki S01E11 [1080p]", HASH11),
            item("[Fansub] Shiki S02E10 [1080p]", HASH12),
            item("[Fansub] Other Show - 10", "f" * 40),
        ]
        matches = candidates(releases, aliases=("Shiki",), season=1,
                             wanted_episodes=Window(6, 1).episodes(10))
        self.assertEqual([m["episode"] for m in matches], [1, 6, 10])
        self.assertEqual([m["episode"] for m in candidates(
            releases, aliases=("Shiki",), season=1,
            wanted_episodes=Window(0, 2).episodes(10))], [10, 11])

    def test_invalid_links_and_ambiguous_seeders_are_skipped(self):
        releases = [item("Shiki - 10", HASH10, seeders=12),
                    item("Shiki - 10", HASH11, seeders=12),
                    {"title": "Shiki - 11", "magnetUrl": "https://example.com/file.torrent"},
                    item("Shiki - 12", "not-an-infohash")]
        self.assertEqual(candidates(releases, aliases=["Shiki"], season=1,
                                    wanted_episodes=[10, 11, 12]), [])
        releases[1]["seeders"] = 13
        winners = candidates(releases, aliases=["Shiki"], season=1, wanted_episodes=[10])
        self.assertEqual([m["info_hash"] for m in winners], [HASH11])

    def test_aliases_are_exact_and_season_qualified(self):
        releases = [
            item("Shiki S02E10", HASH10),
            item("Shiki - 10", HASH11),
            item("Shikii - 10", HASH12),
        ]
        matches = candidates(releases, aliases=("Shiki [S02]",), season=2, wanted_episodes=[10])
        self.assertEqual([m["info_hash"] for m in matches], [HASH10])
        self.assertEqual(candidates(releases, aliases=("Shiki [S02]",), season=1,
                                    wanted_episodes=[10]), [])

    def test_no_arbitrary_data_can_create_targets(self):
        with self.assertRaises(ValueError):
            candidates([], aliases=[], season=1, wanted_episodes=[10])
        with self.assertRaises(ValueError):
            candidates([], aliases=["Shiki"], season=1, wanted_episodes=[True])
        with self.assertRaises(ValueError):
            candidates([], aliases=["Shiki"], season=0, wanted_episodes=[10])


if __name__ == "__main__":
    unittest.main()
