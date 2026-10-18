
import re
import unicodedata


BLOCKED_TERMS = re.compile(
    r"\b(?:OVA|OAV|ONA|SPECIALS?|SP|NCOP|NCED|"
    r"OP|ED|PV|TRAILER|MOVIE|RECAP|EXTRAS?)\b",
    re.IGNORECASE,
)

RANGE_PATTERN = re.compile(
    r"\b(?:E(?:P)?\s*)?\d{1,3}\s*[-~]\s*"
    r"(?:E(?:P)?\s*)?\d{1,3}\b",
    re.IGNORECASE,
)

SEASON_EPISODE_PATTERN = re.compile(
    r"\bS(?P<season>\d{1,2})"
    r"\s*E(?P<episode>\d{1,3})\b",
    re.IGNORECASE,
)


EPISODE_PATTERN = re.compile(
    r"(?:^|[\s\]\)])"
    r"(?:-\s*|Episode\s*|EP\.?\s*|E\s*)"
    r"(?P<episode>\d{1,3})"
    r"(?=$|[\s\[\]\(\)\.]|v\d+\b)",
    re.IGNORECASE,
)


SEASON_MARKER = re.compile(
    r"\b(?:SEASON\s*\d+|S\d{1,2})\b",
    re.IGNORECASE,
)


def normalize_title(value):
    value = unicodedata.normalize("NFKC", value)
    value = value.replace("_", " ")
    value = re.sub(r"[._]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


ADDITIONAL_EPISODE_PATTERN = re.compile(
    r"(?<![A-Za-z0-9])"
    r"(?:EP(?:ISODE)?\.?\s*|E)"
    r"\d{1,3}\b"
    r"|(?<![A-Za-z0-9])"
    r"(?:-|&)\s*\d{1,3}"
    r"(?=$|[\s\[\]\(\)\.]|v\d+\b)",
    re.IGNORECASE,
)




def has_conflicting_episode_identifiers(normalized):
    # Strip explicit season/episode identifiers so that
    # S01E03 is counted as one identifier, not two.
    explicit_matches = list(
        SEASON_EPISODE_PATTERN.finditer(normalized)
    )

    if len(explicit_matches) > 1:
        return True

    remaining = SEASON_EPISODE_PATTERN.sub(
        " ", normalized
    )

    # Recognize "- 01", "E02", "EP03",
    # "Episode 04", and "EP 05".
    ordinary_pattern = re.compile(
        r"(?<![A-Za-z0-9])"
        r"(?:Episode\s*|EP\.?\s*|E\s*|-\s*)"
        r"\d{1,3}"
        r"(?=$|[\s\[\]\(\)\.]|v\d+\b)",
        re.IGNORECASE,
    )

    ordinary_matches = list(
        ordinary_pattern.finditer(remaining)
    )

    total_identifiers = (
        len(explicit_matches) + len(ordinary_matches)
    )

    return total_identifiers > 1


MULTI_EPISODE_SEPARATOR = re.compile(
    r"(?<!\d)\d{1,3}\s*(?:&|\+|,)\s*"
    r"(?:E(?:P)?\s*)?\d{1,3}(?!\d)",
    re.IGNORECASE,
)

EXPLICIT_SEASON_PATTERN = re.compile(
    r"\b(?:Season\s*(?P<named>\d{1,2})"
    r"|S(?P<short>\d{1,2})(?!\d|E\d))\b",
    re.IGNORECASE,
)

def parse_release_title(title):
    normalized = normalize_title(title)

    result = {
        "title": title,
        "season": None,
        "episode": None,
        "accepted": False,
        "reason": None,
    }

    if BLOCKED_TERMS.search(normalized):
        result["reason"] = "SPECIAL_OR_NON_EPISODE"
        return result

    season_labels = list(
        EXPLICIT_SEASON_PATTERN.finditer(normalized)
    )

    if len(season_labels) > 1:
        result["reason"] = "AMBIGUOUS_SEASON"
        return result

    if season_labels:
        match = season_labels[0]
        season_number = int(
            match.group("named") or match.group("short")
        )

        if season_number != 1:
            result["reason"] = "WRONG_SEASON"
            return result

        # Remove the recognized Season 1 / S01 label
        # so the range detector cannot mistake it
        # for the beginning of an episode range.
        normalized = (
            normalized[:match.start()]
            + " "
            + normalized[match.end():]
        )
        
    if RANGE_PATTERN.search(normalized):
        result["reason"] = "EPISODE_RANGE_OR_BATCH"
        return result
    
    if MULTI_EPISODE_SEPARATOR.search(normalized):
        result["reason"] = "MULTIPLE_EPISODE_IDENTIFIERS"
        return result

    if has_conflicting_episode_identifiers(normalized):
        result["reason"] = "MULTIPLE_EPISODE_IDENTIFIERS"
        return result
        
    matches = list(SEASON_EPISODE_PATTERN.finditer(normalized))

    if len(matches) == 1:
        season = int(matches[0].group("season"))
        episode = int(matches[0].group("episode"))

    elif len(matches) > 1:
        result["reason"] = "MULTIPLE_EPISODE_IDENTIFIERS"
        return result

    else:
        if SEASON_MARKER.search(normalized):
            result["reason"] = "AMBIGUOUS_SEASON"
            return result

        matches = list(EPISODE_PATTERN.finditer(normalized))

        if len(matches) != 1:
            result["reason"] = "MISSING_OR_AMBIGUOUS_EPISODE"
            return result

        season = None
        episode = int(matches[0].group("episode"))

    if season is not None and season != 1:
        result["reason"] = "WRONG_SEASON"
        return result

    if not 1 <= episode <= 6:
        result["reason"] = "OUTSIDE_TRIAL_EPISODES"
        return result

    result["season"] = season
    result["episode"] = episode
    result["accepted"] = True
    result["reason"] = "EPISODE_PATTERN_RECOGNIZED"
    return result
