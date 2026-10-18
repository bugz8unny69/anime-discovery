"""Shared verification decision codes and operator-facing definitions.

Use ``VerificationBlocker`` constants instead of scattering literal strings.
The definitions are documentation, not a replacement for verification evidence.
"""

from enum import Enum
from typing import Dict, NamedTuple, Final


#: Evidence marker: the episode audit explicitly reported a numeric offset of 0.
#:
#: Produced by: anime_episode_confidence_v13.evaluate().
#: Consumed by: anime_episode_verification_v16.verify().
#:
#: Meaning: an explicit zero offset was found in the mapping audit.
#: A missing, invalid, or unknown offset is NOT proof of zero offset.
#: This marker is required by V16 but does not by itself verify an episode.
#: Serialized value: EXPLICIT_ZERO_OFFSET (unchanged for DB/JSON compatibility).
EXPLICIT_ZERO_OFFSET: Final[str] = "EXPLICIT_ZERO_OFFSET"
"""Episode numbers match without adjustment.

The episode-mapping data explicitly says AniDB and TVDB use the same episode numbers for this series.
For example, AniDB Episode 2 corresponds to TVDB Season 1 Episode 2.
If this information is missing, the system cannot assume the episode numbers match and must wait for confirmation.
"""


class EpisodeMappingEvidence(str, Enum):
    """Episode-ordering evidence emitted by V13 and consumed by V16.

    Hover over this class for the evidence contract. The value remains the
    existing serialized marker for database and JSON compatibility.
    """

    #: Explicit integer episode offset 0 was found in the episode audit.
    #: Missing offset does not count. This is necessary but not sufficient
    #: to verify the whole episode identity; V16 checks other evidence too.
    EXPLICIT_ZERO_OFFSET = "EXPLICIT_ZERO_OFFSET"


class VerificationBlocker(str, Enum):
    """Stable, machine-readable reasons that episode approval is blocked.

    These values can appear in database evidence JSON and diagnostic output.
    Do not rename serialized values without a backward-compatibility alias.
    """

    #: AniDB-to-TVDB episode ordering has not been confirmed by the verifier.
    #:
    #: Cause: The verification report lacks the EXPLICIT_ZERO_OFFSET evidence
    #: marker. This is a specific rule in the current V16 verifier; it does
    #: not establish that the proposed episode mapping is wrong.
    #:
    #: Resolution: Verify the episode-ordering evidence and its provenance.
    #: Approval: Remains blocked until the verifier accepts the evidence.
    #: Retry: Appropriate when mapping metadata changes or becomes available.
    EPISODE_ORDERING_MAPPING_NOT_CONFIRMED = "EPISODE_ORDERING_MAPPING_NOT_CONFIRMED"


class BlockerDefinition(NamedTuple):
    """Human-readable details associated with a verification blocker."""

    meaning: str
    cause: str
    resolution: str
    retry: str
    automatic_approval: bool


BLOCKER_DEFINITIONS: Dict[VerificationBlocker, BlockerDefinition] = {
    VerificationBlocker.EPISODE_ORDERING_MAPPING_NOT_CONFIRMED: BlockerDefinition(
        meaning="AniDB-to-TVDB episode ordering is not yet confirmed.",
        cause="The current V16 verifier did not receive EXPLICIT_ZERO_OFFSET evidence.",
        resolution="Inspect mapping evidence, provenance, and the verifier's evidence list.",
        retry="Retry after obtaining new or corrected mapping evidence.",
        automatic_approval=False,
    ),
}

# Historical values in stored verification JSON must remain interpretable.
LEGACY_BLOCKER_ALIASES: Dict[str, VerificationBlocker] = {
    "EPISODE_OFFSET_NOT_INDEPENDENTLY_VERIFIED": (
        VerificationBlocker.EPISODE_ORDERING_MAPPING_NOT_CONFIRMED
    ),
}


def normalize_blocker(code: str) -> str:
    """Return the canonical blocker code, preserving unknown codes.

    Args:
        code: A blocker from a new or historical verification record.

    Returns:
        Canonical serialized code, or the original code if not recognized.

    This does not modify stored records or grant episode approval.
    """
    return LEGACY_BLOCKER_ALIASES.get(code, code).value if code in LEGACY_BLOCKER_ALIASES else code


def describe_blocker(code: str) -> BlockerDefinition | None:
    """Look up documentation for a canonical or historical blocker code.

    Unknown codes return None rather than inventing an explanation.
    """
    normalized = normalize_blocker(code)
    try:
        member = VerificationBlocker(normalized)
    except ValueError:
        return None
    return BLOCKER_DEFINITIONS.get(member)
