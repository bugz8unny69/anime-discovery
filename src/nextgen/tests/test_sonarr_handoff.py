"""Offline Sonarr handoff admission tests; never contacts a torrent client."""
import unittest
from unittest.mock import patch

from src.nextgen.acquisition.contracts import AcquisitionInput
from src.nextgen.acquisition.metadata import AcquisitionConflict, Manifest, TorrentFile
from src.nextgen.acquisition.settings import SizeLimits
from src.nextgen.acquisition.sonarr_handoff import admit_candidate, AdmittedCandidate
from src.nextgen.acquisition.sonarr_search import DiscoveryPolicy, Release, SearchResult
from src.nextgen.sonarr_episode import VerifiedEpisode

HASH = "a" * 40
OTHER = "b" * 40
IDENTITY = VerifiedEpisode(100, 200, 1, 10)


def candidate(*, digest=HASH, scope="exact", resolution=1080, seeders=20):
    return Release(
        "Example S01E10", "Nyaa", "torrent", "WEBDL-1080p", resolution,
        0, seeders, 0, 300000000, False, ("Sonarr quality disapproved",),
        (22,), scope, digest,
        "magnet:?xt=urn:btih:" + digest, scope == "exact",
    )


def source(*, digest=HASH):
    return AcquisitionInput(1, 2, 3, 4, digest, "a" * 64, 10, 1, 10, "Example")


class SonarrHandoffTests(unittest.TestCase):
    def test_rejects_unbound_candidate_other_hash_and_unverified_context(self):
        good = candidate()
        result = SearchResult(11, 22, (good,))
        cases = (
            {"release": candidate()},
            {"source": source(digest=OTHER)},
            {"identity": VerifiedEpisode(100, 200, 2, 10)},
            {"release": candidate(scope="pack")},
            {"release": candidate(resolution=2160)},
            {"release": candidate(seeders=0)},
        )
        base = dict(result=result, release=good, identity=IDENTITY,
                    source=source(), metainfo=b"not-a-torrent",
                    policy=DiscoveryPolicy())
        for changes in cases:
            with self.subTest(changes=tuple(changes)), self.assertRaises(AcquisitionConflict):
                admit_candidate(**(base | changes))

    def test_accepted_candidate_still_requires_hash_checked_manifest(self):
        chosen = candidate()
        kwargs = dict(result=SearchResult(11, 22, (chosen,)), release=chosen,
                      identity=IDENTITY, source=source(), metainfo=b"torrent-bytes",
                      policy=DiscoveryPolicy(), limits=SizeLimits(600, 3000))
        with self.assertRaises(ValueError):
            admit_candidate(**kwargs)
        manifest = Manifest(HASH, "0" * 64, (TorrentFile(0, "Example S01E10.mkv", 100000000),), 0)
        with patch("src.nextgen.acquisition.sonarr_handoff.parse_metainfo", return_value=manifest) as parsed:
            admitted = admit_candidate(**kwargs)
        parsed.assert_called_once_with(b"torrent-bytes", HASH)
        self.assertIsInstance(admitted, AdmittedCandidate)
        self.assertEqual(admitted.source.info_hash, HASH)
        self.assertNotIn("magnet:", repr(admitted))


if __name__ == "__main__":
    unittest.main()
