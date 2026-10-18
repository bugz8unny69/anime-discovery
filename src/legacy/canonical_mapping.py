
from series_identity import validate_series_identity


def validate_canonical_mapping(
    release,
    expected_title,
    episode_map,
    aliases=(),
):
    """
    Resolve a release episode through an explicitly trusted map.

    episode_map format:
        {
            1: (1, 1),
            2: (1, 2),
        }

    Key: release episode number
    Value: (canonical season, canonical episode)

    No inferred identity or implicit episode mapping.
    """
    result = {
        "accepted": False,
        "reason": None,
        "release_episode": None,
        "canonical_season": None,
        "canonical_episode": None,
    }

    identity = validate_series_identity(
        release,
        expected_title,
        aliases,
    )

    if not identity["accepted"]:
        result["reason"] = identity["reason"]
        return result

    release_episode = identity["episode"]
    result["release_episode"] = release_episode

    if not isinstance(episode_map, dict):
        result["reason"] = "INVALID_EPISODE_MAP"
        return result

    # Validate the entire map, not just the requested entry.
    # Reject malformed and conflicting mappings.
    canonical_targets = set()

    for source, target in episode_map.items():
        if type(source) is not int or source < 1:
            result["reason"] = "INVALID_EPISODE_MAP"
            return result

        if (
            not isinstance(target, tuple)
            or len(target) != 2
            or any(type(n) is not int for n in target)
        ):
            result["reason"] = "INVALID_EPISODE_MAP"
            return result

        season, episode = target

        if season != 1 or not 1 <= episode <= 6:
            result["reason"] = "OUTSIDE_CANONICAL_TRIAL"
            return result

        if target in canonical_targets:
            result["reason"] = "CONFLICTING_EPISODE_MAP"
            return result

        canonical_targets.add(target)

    if release_episode not in episode_map:
        result["reason"] = "MISSING_EPISODE_MAPPING"
        return result

    season, episode = episode_map[release_episode]

    result["accepted"] = True
    result["reason"] = "TRUSTED_CANONICAL_MAPPING"
    result["canonical_season"] = season
    result["canonical_episode"] = episode

    return result
