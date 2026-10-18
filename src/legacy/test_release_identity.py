
from release_identity import parse_release_title


cases = [
    # Title, expected accepted, expected episode
    ("[SubsPlease] Example Anime - 01 [1080p].mkv", True, 1),
    ("[Group] Example Anime - 02 [Dual Audio].mkv", True, 2),
    ("Example Anime S01E03 1080p", True, 3),
    ("Example Anime Episode 04", True, 4),
    ("Example Anime - 06v2 [BD]", True, 6),

    ("Example Anime - 07", False, None),
    ("Example Anime S02E01", False, None),
    ("Example Anime - 01-06", False, None),
    ("Example Anime - 01~03", False, None),
    ("Example Anime OVA - 01", False, None),
    ("Example Anime Special - 01", False, None),
    ("Example Anime Movie - 01", False, None),
    ("Example Anime Season 2 - 01", False, None),
    ("Example Anime Complete Batch", False, None),
    ("Example Anime", False, None),
]

for title, expected, expected_episode in cases:
    result = parse_release_title(title)

    print(
        f"{'PASS' if result['accepted'] == expected and result['episode'] == expected_episode else 'FAIL'} "
        f"{title} -> {result['reason']}"
    )

    assert result["accepted"] == expected, result
    assert result["episode"] == expected_episode, result


# Ambiguity and conflicting identifier tests
ambiguous_cases = [
    "Example Anime S01E03 E04",
    "Example Anime S01E03 S01E04",
    "Example Anime S01E03 - 04",
    "Example Anime - 01 - 02",
    "Example Anime - 01 & 02",
    "Example Anime E01 E02",
    "Example Anime S01E03 S02E03",
    "Example Anime - 01 [Episode 02]",
]

for title in ambiguous_cases:
    result = parse_release_title(title)

    print(
        f"{'PASS' if not result['accepted'] else 'FAIL'} "
        f"{title} -> {result['reason']}"
    )

    assert not result["accepted"], (
        f"Ambiguous title incorrectly accepted: {title}"
    )

print("All ambiguity tests passed.")

print("\nAll release-title parsing tests passed.")


# Phase 2X-C: season and numeric-title regression tests
hardening_cases = [
    # Title, accepted, episode, reason
    (
        "Example Anime Season 2 - 01",
        False, None, "WRONG_SEASON",
    ),
    (
        "Example Anime Season 1 - 01",
        True, 1, "EPISODE_PATTERN_RECOGNIZED",
    ),
    (
        "Example Anime S02 - 01",
        False, None, "WRONG_SEASON",
    ),
    (
        "Example Anime S01 - 02",
        True, 2, "EPISODE_PATTERN_RECOGNIZED",
    ),
    (
        "[Group] 86 Eighty-Six - 01 [1080p]",
        True, 1, "EPISODE_PATTERN_RECOGNIZED",
    ),
    (
        "[Group] 3-gatsu no Lion - 02 [1080p]",
        True, 2, "EPISODE_PATTERN_RECOGNIZED",
    ),
    (
        "[Group] Example Anime - 01 [10bit 1080p]",
        True, 1, "EPISODE_PATTERN_RECOGNIZED",
    ),
]

for title, expected, expected_episode, expected_reason in hardening_cases:
    result = parse_release_title(title)

    passed = (
        result["accepted"] == expected
        and result["episode"] == expected_episode
        and result["reason"] == expected_reason
    )

    print(
        f"{'PASS' if passed else 'FAIL'} "
        f"{title} -> {result['reason']}"
    )

    assert passed, result

print("All Phase 2X-C hardening tests passed.")

