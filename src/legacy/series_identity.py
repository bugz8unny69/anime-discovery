
import re
import unicodedata

from release_identity import parse_release_title


def canonical_title(value):
    """Normalize presentation differences, not title meaning."""
    value = unicodedata.normalize("NFKC", value)
    value = value.casefold()

    # Normalize separators without changing word order.
    value = re.sub(r"[._]+", " ", value)
    value = re.sub(r"\s+", " ", value)

    return value.strip()


def release_series_title(release):
    """Extract a series title only from a narrow release format."""
    if not isinstance(release, str):
        return None

    text = release.strip()

    # Remove one conventional release-group prefix.
    text = re.sub(r"^\[[^\[\]]+\]\s*", "", text)

    # Accept only the unambiguous 'Title - NN' form.
    match = re.fullmatch(
        r"(?P<title>.+?)\s+-\s+"
        r"(?P<episode>\d{1,3})(?:v\d+)?"
        r"(?:\s+\[[^\[\]]+\])*"
        r"(?:\.(?:mkv|mp4))?",
        text,
        re.IGNORECASE,
    )

    if not match:
        return None

    return match.group("title").strip()


def validate_series_identity(release, expected_title, aliases=()):
    """Fail closed unless the release title matches an approved name."""
    result = {
        "accepted": False,
        "reason": None,
        "matched_title": None,
        "episode": None,
    }

    parsed = parse_release_title(release)

    if not parsed["accepted"]:
        result["reason"] = parsed["reason"]
        return result

    extracted = release_series_title(release)

    if extracted is None:
        result["reason"] = "UNSUPPORTED_RELEASE_FORMAT"
        return result

    if not isinstance(expected_title, str) or not expected_title.strip():
        result["reason"] = "MISSING_TRUSTED_TITLE"
        return result

    approved = [expected_title, *aliases]

    for title in approved:
        if not isinstance(title, str) or not title.strip():
            continue

        if canonical_title(extracted) == canonical_title(title):
            result["accepted"] = True
            result["reason"] = "TRUSTED_TITLE_MATCH"
            result["matched_title"] = title
            result["episode"] = parsed["episode"]
            return result

    result["reason"] = "SERIES_TITLE_MISMATCH"
    return result
