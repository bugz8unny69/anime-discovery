
from canonical_mapping import validate_canonical_mapping


def validate_approved_mapping(
    release,
    expected_series_id,
    expected_title,
    mapping_record,
    aliases=(),
):
    """
    Require an explicitly approved, series-bound mapping record.

    This validates the record but does not establish the
    trustworthiness of whoever supplied it.
    """
    result = {
        "accepted": False,
        "reason": None,
        "release_episode": None,
        "canonical_season": None,
        "canonical_episode": None,
    }

    if (
        type(expected_series_id) is not int
        or expected_series_id < 1
    ):
        result["reason"] = "INVALID_EXPECTED_SERIES_ID"
        return result

    if not isinstance(mapping_record, dict):
        result["reason"] = "INVALID_MAPPING_RECORD"
        return result

    required = {
        "series_id",
        "approved",
        "approval_source",
        "episode_map",
    }

    if set(mapping_record) != required:
        result["reason"] = "INVALID_MAPPING_RECORD"
        return result

    if (
        type(mapping_record["series_id"]) is not int
        or mapping_record["series_id"] < 1
    ):
        result["reason"] = "INVALID_MAPPING_RECORD"
        return result

    if mapping_record["series_id"] != expected_series_id:
        result["reason"] = "MAPPING_SERIES_MISMATCH"
        return result

    if mapping_record["approved"] is not True:
        result["reason"] = "MAPPING_NOT_APPROVED"
        return result

    # This is an allowlist of declared approval origins,
    # not proof that the declaration is authentic.
    if mapping_record["approval_source"] != "manual":
        result["reason"] = "UNTRUSTED_APPROVAL_SOURCE"
        return result

    mapped = validate_canonical_mapping(
        release,
        expected_title,
        mapping_record["episode_map"],
        aliases,
    )

    result.update(mapped)
    return result
