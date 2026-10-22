"""Stable, presentation-ready operational reasons; no dashboard/runtime dependency.

The coordinator decides state/retry timing. Descriptions are never evaluated
as workflow instructions, and context is always sanitized before persistence.
"""
from dataclasses import dataclass
from types import MappingProxyType

@dataclass(frozen=True)
class Reason:
    code: str
    description: str
    message: str
    action: str
    severity: str
    retryable: bool

_ENTRIES = (
    Reason("IDENTITY_INCOMPLETE", "Required provider-verified identity facts are missing.",
           "Anime identification is incomplete.", "Review missing verification details or allow a scheduled retry.",
           "WARNING", True),
    Reason("IDENTITY_INVALID", "The resolved identity failed AnimeSeries validation.",
           "Anime identification could not be verified.", "Review the identification results.",
           "WARNING", False),
    Reason("IDENTITY_CONFLICT", "Verified identifiers conflict with stored identity.",
           "Conflicting anime information needs review.", "Review the conflicting identifiers.",
           "WARNING", False),
    Reason("PROVIDER_UNAVAILABLE", "A provider request could not complete due to availability.",
           "An information provider is temporarily unavailable.", "The operation can be retried.",
           "WARNING", True),
    Reason("JOB_LEASE_EXPIRED", "A running job lease expired before completion.",
           "Processing was interrupted.", "The system can safely retry the work.",
           "WARNING", True),
    Reason("JOB_HANDLER_FAILED", "A job handler failed unexpectedly.",
           "An unexpected processing error occurred.", "Review the job details.",
           "ERROR", True),
    Reason("JOB_RETRY_EXHAUSTED", "A job exceeded its allowed attempts.",
           "Automatic retries have stopped.", "Review the job before retrying manually.",
           "ERROR", False),
    Reason("STORAGE_UNAVAILABLE", "An operational SQLite transaction could not be committed.",
           "Processing is temporarily unavailable.", "Check database health and storage.",
           "ERROR", True),
    Reason("UNSUPPORTED_JOB_KIND", "No handler is registered for this job type.",
           "This type of work cannot be processed.", "Check the installed components.",
           "ERROR", False),
)
REGISTRY = MappingProxyType({item.code: item for item in _ENTRIES})
assert len(REGISTRY) == len(_ENTRIES)

def get_reason(code: str) -> Reason | None:
    """Unknown historical codes are allowed and displayed generically."""
    return REGISTRY.get(code) if isinstance(code, str) else None

def display_reason(code: str) -> dict:
    entry = get_reason(code)
    if entry is None:
        return {"code": code if isinstance(code, str) else "UNKNOWN",
                "message": "Additional processing information is available.",
                "action": "Review the job history.", "severity": "WARNING",
                "retryable": None}
    return {"code": entry.code, "message": entry.message,
            "action": entry.action, "severity": entry.severity,
            "retryable": entry.retryable}

def safe_details(*, missing_fields=(), retry_at_ms=None) -> dict:
    """Only allow explicitly bounded, structured, non-secret history details."""
    if not isinstance(missing_fields, (list, tuple)) or len(missing_fields) > 20:
        raise ValueError("invalid missing_fields")
    allowed = {"anime.anidb_id", "anime.tvdb_series_id", "anime.title",
               "episodes[].anidb_episode_id"}
    if any(type(name) is not str or name not in allowed for name in missing_fields):
        raise ValueError("invalid missing field")
    if retry_at_ms is not None and (type(retry_at_ms) is not int or retry_at_ms < 0):
        raise ValueError("invalid retry time")
    details = {}
    if missing_fields:
        details["missing_fields"] = sorted(set(missing_fields))
    if retry_at_ms is not None:
        details["retry_at_ms"] = retry_at_ms
    return details
