
from canonical_mapping import validate_canonical_mapping


RELEASE = "[Group] Example Anime - 02 [1080p].mkv"

cases = [
    (
        "Trusted identity mapping",
        {1: (1, 1), 2: (1, 2)},
        True,
        "TRUSTED_CANONICAL_MAPPING",
        (1, 2),
    ),
    (
        "Explicit alternate numbering",
        {2: (1, 1)},
        True,
        "TRUSTED_CANONICAL_MAPPING",
        (1, 1),
    ),
    (
        "Missing mapping",
        {1: (1, 1)},
        False,
        "MISSING_EPISODE_MAPPING",
        (None, None),
    ),
    (
        "Wrong canonical season",
        {2: (2, 2)},
        False,
        "OUTSIDE_CANONICAL_TRIAL",
        (None, None),
    ),
    (
        "Outside six-episode trial",
        {2: (1, 7)},
        False,
        "OUTSIDE_CANONICAL_TRIAL",
        (None, None),
    ),
    (
        "Conflicting canonical targets",
        {1: (1, 2), 2: (1, 2)},
        False,
        "CONFLICTING_EPISODE_MAP",
        (None, None),
    ),
    (
        "Malformed target",
        {2: "S01E02"},
        False,
        "INVALID_EPISODE_MAP",
        (None, None),
    ),
    (
        "Boolean episode key",
        {True: (1, 1), 2: (1, 2)},
        False,
        "INVALID_EPISODE_MAP",
        (None, None),
    ),
]

for name, mapping, expected, reason, target in cases:
    result = validate_canonical_mapping(
        RELEASE,
        "Example Anime",
        mapping,
    )

    actual_target = (
        result["canonical_season"],
        result["canonical_episode"],
    )

    passed = (
        result["accepted"] == expected
        and result["reason"] == reason
        and actual_target == target
    )

    print(
        f"{'PASS' if passed else 'FAIL'} "
        f"{name} -> {result['reason']}"
    )

    assert passed, result

# A mapping must never override a mismatched series identity.
mismatch = validate_canonical_mapping(
    "[Group] Different Anime - 02 [1080p].mkv",
    "Example Anime",
    {2: (1, 2)},
)

assert not mismatch["accepted"]
assert mismatch["reason"] == "SERIES_TITLE_MISMATCH"
print("PASS Series mismatch cannot be overridden by mapping")

print("\nAll canonical mapping tests passed.")
