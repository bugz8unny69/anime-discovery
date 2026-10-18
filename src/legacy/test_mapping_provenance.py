
from mapping_provenance import validate_approved_mapping


RELEASE = "[Group] Example Anime - 02 [1080p].mkv"

APPROVED = {
    "series_id": 7,
    "approved": True,
    "approval_source": "manual",
    "episode_map": {
        1: (1, 1),
        2: (1, 2),
    },
}


def check(name, record, expected_reason, accepted=False):
    result = validate_approved_mapping(
        RELEASE,
        7,
        "Example Anime",
        record,
    )

    passed = (
        result["accepted"] is accepted
        and result["reason"] == expected_reason
    )

    print(
        f"{'PASS' if passed else 'FAIL'} "
        f"{name} -> {result['reason']}"
    )

    assert passed, result


check(
    "Approved mapping",
    APPROVED,
    "TRUSTED_CANONICAL_MAPPING",
    True,
)

check(
    "Wrong series",
    {**APPROVED, "series_id": 8},
    "MAPPING_SERIES_MISMATCH",
)

check(
    "Unapproved mapping",
    {**APPROVED, "approved": False},
    "MAPPING_NOT_APPROVED",
)

check(
    "Indexer approval source",
    {**APPROVED, "approval_source": "indexer"},
    "UNTRUSTED_APPROVAL_SOURCE",
)

check(
    "Release metadata approval source",
    {**APPROVED, "approval_source": "release_title"},
    "UNTRUSTED_APPROVAL_SOURCE",
)

check(
    "Missing approval field",
    {
        key: value
        for key, value in APPROVED.items()
        if key != "approved"
    },
    "INVALID_MAPPING_RECORD",
)

check(
    "Unexpected metadata field",
    {**APPROVED, "torrent_supplied": True},
    "INVALID_MAPPING_RECORD",
)

check(
    "Invalid approval type",
    {**APPROVED, "approved": 1},
    "MAPPING_NOT_APPROVED",
)

check(
    "Conflicting canonical targets",
    {
        **APPROVED,
        "episode_map": {
            1: (1, 2),
            2: (1, 2),
        },
    },
    "CONFLICTING_EPISODE_MAP",
)

print("\nAll mapping provenance tests passed.")
