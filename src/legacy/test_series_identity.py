
from series_identity import validate_series_identity


cases = [
    (
        "[Group] Example Anime - 01 [1080p].mkv",
        "Example Anime",
        (),
        True,
        "TRUSTED_TITLE_MATCH",
    ),
    (
        "[Group] Different Anime - 01 [1080p].mkv",
        "Example Anime",
        (),
        False,
        "SERIES_TITLE_MISMATCH",
    ),
    (
        "[Group] 86 Eighty-Six - 01 [1080p].mkv",
        "86 Eighty-Six",
        (),
        True,
        "TRUSTED_TITLE_MATCH",
    ),
    (
        "[Group] Example Anime - 02 [1080p].mkv",
        "Example Anime",
        (),
        True,
        "TRUSTED_TITLE_MATCH",
    ),
    (
        "[Group] Example Anime - 01 [1080p].mkv",
        "Example Anime Season 2",
        (),
        False,
        "SERIES_TITLE_MISMATCH",
    ),
    (
        "[Group] Example Anime - 01 [1080p].mkv",
        "Different Anime",
        ("Example Anime",),
        True,
        "TRUSTED_TITLE_MATCH",
    ),
    (
        "[Group] Example Anime - 01-06 [1080p].mkv",
        "Example Anime",
        (),
        False,
        "EPISODE_RANGE_OR_BATCH",
    ),
    (
        "[Group] Example Anime OVA - 01 [1080p].mkv",
        "Example Anime",
        (),
        False,
        "SPECIAL_OR_NON_EPISODE",
    ),
    (
        "Example Anime S01E03 1080p",
        "Example Anime",
        (),
        False,
        "UNSUPPORTED_RELEASE_FORMAT",
    ),
]

for release, expected_title, aliases, accepted, reason in cases:
    result = validate_series_identity(
        release,
        expected_title,
        aliases,
    )

    passed = (
        result["accepted"] == accepted
        and result["reason"] == reason
    )

    print(
        f"{'PASS' if passed else 'FAIL'} "
        f"{release} -> {result['reason']}"
    )

    assert passed, result

print("\nAll trusted series identity tests passed.")
