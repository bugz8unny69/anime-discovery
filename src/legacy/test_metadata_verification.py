"""Offline regression suite; never opens production controller or network."""
from metadata_verification import verify_candidate

RELEASE = "[Group] Example Anime - 02 [1080p].mkv"
GOOD = dict(series_id=7, source="trusted_fixture", external_id="fixture-007",
            canonical_title="Example Anime", season=1, verified=True,
            episode_map={1: (1, 1), 2: (1, 2)})


def check(name, reason, record=GOOD, release=RELEASE, sid=7, title="Example Anime", aliases=()):
    result = verify_candidate(release, sid, title, record, aliases)
    assert result["reason"] == reason, (name, result)
    assert result["authorized"] is (reason == "VERIFIED_MAPPING_CANDIDATE"), (name, result)
    if result["authorized"]:
        assert (result["canonical_season"], result["canonical_episode"]) == (1, 2), result
    print("PASS", name, "->", reason)


check("verified fixture", "VERIFIED_MAPPING_CANDIDATE")
check("missing record", "NO_TRUSTED_METADATA", None)
check("unverified record", "METADATA_NOT_VERIFIED", {**GOOD, "verified": False})
check("truthy string not verified", "METADATA_NOT_VERIFIED", {**GOOD, "verified": "true"})
check("indexer self-attestation", "UNSUPPORTED_METADATA_SOURCE", {**GOOD, "source": "indexer"})
check("torrent self-attestation", "UNSUPPORTED_METADATA_SOURCE", {**GOOD, "source": "torrent"})
check("wrong internal series", "METADATA_SERIES_MISMATCH", {**GOOD, "series_id": 8})
check("wrong metadata season", "METADATA_SEASON_MISMATCH", {**GOOD, "season": 2})
check("wrong metadata title", "METADATA_TITLE_MISMATCH", {**GOOD, "canonical_title": "Other Anime"})
check("missing external id", "INVALID_METADATA_RECORD", {**GOOD, "external_id": ""})
check("extra metadata field", "INVALID_METADATA_RECORD", {**GOOD, "torrent_approved": True})
check("missing episode mapping", "MISSING_EPISODE_MAPPING", {**GOOD, "episode_map": {1: (1, 1)}})
check("conflicting mapping", "CONFLICTING_EPISODE_MAP", {**GOOD, "episode_map": {1: (1, 2), 2: (1, 2)}})
check("different release title", "SERIES_TITLE_MISMATCH", release="[Group] Other Anime - 02 [1080p].mkv")
check("batch release", "EPISODE_RANGE_OR_BATCH", release="[Group] Example Anime - 01-06 [1080p].mkv")
check("wrong series input", "METADATA_SERIES_MISMATCH", sid=9)
check("alias cannot override trusted title", "METADATA_TITLE_MISMATCH", {**GOOD, "canonical_title": "Other Anime"}, aliases=("Other Anime",))
print("\nAll 17 offline metadata verification tests passed.")
