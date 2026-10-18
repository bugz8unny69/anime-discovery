"""Phase 2X-H: pure, offline metadata verification. No network or DB writes.

The caller MUST obtain trusted_record from a separately authenticated metadata
adapter. Never construct it from torrent/indexer payloads.
"""
from canonical_mapping import validate_canonical_mapping


def verify_candidate(release, expected_series_id, expected_title, trusted_record, aliases=()):
    def deny(reason):
        return {"authorized": False, "reason": reason, "canonical_season": None,
                "canonical_episode": None, "release_episode": None}

    if type(expected_series_id) is not int or expected_series_id < 1:
        return deny("INVALID_SERIES_ID")
    if not isinstance(expected_title, str) or not expected_title.strip():
        return deny("INVALID_EXPECTED_TITLE")
    if not isinstance(trusted_record, dict):
        return deny("NO_TRUSTED_METADATA")
    required = {"series_id", "source", "external_id", "canonical_title", "season", "verified", "episode_map"}
    if set(trusted_record) != required:
        return deny("INVALID_METADATA_RECORD")
    if trusted_record["verified"] is not True:
        return deny("METADATA_NOT_VERIFIED")
    if trusted_record["source"] not in ("trusted_fixture",):
        return deny("UNSUPPORTED_METADATA_SOURCE")
    if not isinstance(trusted_record["external_id"], str) or not trusted_record["external_id"].strip():
        return deny("INVALID_METADATA_RECORD")
    if type(trusted_record["series_id"]) is not int or trusted_record["series_id"] != expected_series_id:
        return deny("METADATA_SERIES_MISMATCH")
    if type(trusted_record["season"]) is not int or trusted_record["season"] != 1:
        return deny("METADATA_SEASON_MISMATCH")
    # The trusted canonical title must be the expected title. Aliases are used
    # solely to match the release, never to override metadata identity.
    from series_identity import canonical_title
    if not isinstance(trusted_record["canonical_title"], str) or canonical_title(trusted_record["canonical_title"]) != canonical_title(expected_title):
        return deny("METADATA_TITLE_MISMATCH")
    if not isinstance(aliases, (tuple, list)) or any(not isinstance(x, str) for x in aliases):
        return deny("INVALID_ALIASES")
    mapped = validate_canonical_mapping(release, expected_title, trusted_record["episode_map"], aliases)
    if not mapped["accepted"]:
        return deny(mapped["reason"])
    return {"authorized": True, "reason": "VERIFIED_MAPPING_CANDIDATE",
            "release_episode": mapped["release_episode"],
            "canonical_season": mapped["canonical_season"],
            "canonical_episode": mapped["canonical_episode"]}
