"""Stable, presentation-ready operational reasons; no dashboard/runtime dependency.

The worker decides state/retry timing. Descriptions are never evaluated
as workflow instructions. Callers must validate details before persistence.
"""
from dataclasses import dataclass
from types import MappingProxyType
import re

@dataclass(frozen=True)
class Reason:
    code: str
    description: str
    message: str
    action: str
    severity: str
    retryable: bool | None

_ENTRIES = (
    Reason("IDENTITY_INCOMPLETE", "Required provider-verified identity facts are missing.",
           "Anime identification is incomplete.", "Review the missing identification details.",
           "WARNING", None),
    Reason("IDENTITY_INVALID", "The resolved identity failed AnimeSeries validation.",
           "Anime identification could not be verified.", "Review the identification results.",
           "WARNING", False),
    Reason("IDENTITY_CONFLICT", "Verified identifiers conflict with stored identity.",
           "Conflicting anime information needs review.", "Review the conflicting identifiers.",
           "WARNING", False),
    Reason("PROVIDER_UNAVAILABLE", "A provider request could not complete due to availability.",
           "An information provider is temporarily unavailable.", "The operation can be retried.",
           "WARNING", True),
    Reason("PROVIDER_RESPONSE_INVALID", "A provider response failed bounded decoding or structural checks.",
           "An information provider returned an unusable response.", "Retry later or review provider availability.", "WARNING", None),
    Reason("PROVIDER_AUTH_FAILED", "Provider authentication or authorization failed.",
           "An information provider could not authorize access.", "Review the provider access settings.", "WARNING", False),
    Reason("JOB_LEASE_EXPIRED", "A running job lease expired before completion.",
           "Processing was interrupted.", "Check the interrupted work and its recovery status.",
           "WARNING", True),
    Reason("JOB_HANDLER_FAILED", "A job handler failed unexpectedly.",
           "An unexpected processing error occurred.", "Review the job details.",
           "ERROR", None),
    Reason("JOB_RETRY_EXHAUSTED", "A job reached its allowed attempt limit.",
           "Automatic retries have stopped.", "Review the job before retrying manually.",
           "ERROR", False),
    Reason("STORAGE_UNAVAILABLE", "Storage access failed; the cause and commit outcome require investigation.",
           "Processing is temporarily unavailable.", "Check database health and storage.",
           "ERROR", None),
    Reason("UNSUPPORTED_JOB_KIND", "No handler is registered for this job type.",
           "This type of work cannot be processed.", "Check the installed components.",
           "ERROR", False),
    Reason("CONFIGURATION_INVALID", "Configuration shape, field or value failed validation.",
           "Configuration could not be validated.", "Review the configuration and supported settings.",
           "WARNING", False),
    Reason("CONFIGURATION_CONFLICT", "The saved revision or migration source changed.",
           "Configuration changed before this update could be applied.",
           "Refresh the configuration and review the changes again.", "WARNING", False),
    Reason("CONFIGURATION_MIGRATION_REQUIRED", "An older supported configuration needs explicit conversion.",
           "Configuration needs an upgrade.", "Preview and apply the configuration migration.",
           "WARNING", False),
    Reason("CONFIGURATION_STORAGE_FAILED", "Safe configuration access or publication failed.",
           "Configuration storage is unavailable.", "Check the service account permissions and storage.",
           "ERROR", None),
    Reason("CONFIGURATION_DURABILITY_UNCONFIRMED", "Rename succeeded but directory synchronization failed.",
           "Configuration was updated, but durable storage could not be confirmed.",
           "Read the current configuration and check storage before retrying.", "ERROR", None),
    Reason("MAINTENANCE_PENDING", "A durable maintenance request blocks new admissions.",
           "New work is paused for maintenance.", "Wait for maintenance to finish.", "INFO", None),
    Reason("MAINTENANCE_BUSY", "Existing admissions or another maintenance controller still hold a lock.",
           "Existing work is still finishing.", "Check maintenance progress before trying again.", "INFO", None),
    Reason("MAINTENANCE_FAILED", "Maintenance state, ownership or storage needs review.",
           "Maintenance state needs review.", "Check maintenance status before resuming work.", "ERROR", None),
    Reason("DATABASE_VERSION_UNSUPPORTED", "The database version is unversioned, newer or outside the supported upgrade path.",
           "This database version cannot be upgraded by this application.",
           "Verify the application version and selected database.", "ERROR", False),
    Reason("DATABASE_SCHEMA_INVALID", "Schema, integrity or foreign-key validation failed.",
           "The database does not match the expected application structure.",
           "Keep maintenance active and review database health.", "ERROR", False),
    Reason("DATABASE_MIGRATION_CONFLICT", "Database structure/version or packaged migration inputs changed after preview.",
           "The database upgrade plan changed.", "Preview the upgrade again before applying it.", "WARNING", False),
    Reason("DATABASE_MIGRATION_FAILED", "Upgrade or backup failed; earlier version steps may already be committed.",
           "Database upgrade stopped. Maintenance remains active.",
           "Review the current database version and backup before continuing.", "ERROR", None),

    Reason("JOB_WAITING", "A handler deferred a normal prerequisite or external-work wait.",
           "Work is waiting for a prerequisite.", "Check the recorded waiting condition.", "INFO", None),
    Reason("JOB_STATE_INVALID", "A queued job has inconsistent lifecycle bookkeeping.",
           "Job progress needs review.", "Review the job history before resuming work.", "ERROR", False),
    Reason("JOB_PAYLOAD_INVALID", "A queued payload is invalid or exceeds the worker bound.",
           "Job information could not be validated.", "Review the queued job before trying again.", "ERROR", False),
    Reason("WORKER_NOT_READY", "No trusted job handlers are registered for execution.",
           "The worker is not ready to process jobs.", "Install and register the required job handlers.", "ERROR", False),

)
REGISTRY = MappingProxyType({item.code: item for item in _ENTRIES})
if len(REGISTRY) != len(_ENTRIES):
    raise ValueError("duplicate reason code")

_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}", re.ASCII)
_MAX_INTEGER = (1 << 63) - 1
_FIELDS = frozenset({
    "schema_version", "anime.anidb_id", "anime.tvdb_series_id", "anime.title",
    "anime.english_title", "anime.original_title", "anime.type", "anime.year",
    "episodes", "episodes[].anidb_episode_id", "episodes[].anidb_episode_number",
    "episodes[].title", "episodes[].type", "episodes[].tvdb_placement",
    "episodes[].tvdb_placement.season", "episodes[].tvdb_placement.episode",
    "attributes",
})


def _code_or_unknown(code) -> str:
    # No arbitrary values, control characters, or unbounded historical strings.
    return code if type(code) is str and _CODE.fullmatch(code) else "UNKNOWN"

def get_reason(code: str) -> Reason | None:
    """Unknown historical codes are allowed and displayed generically."""
    return REGISTRY.get(code) if type(code) is str else None

def display_reason(code: str) -> dict:
    entry = get_reason(code)
    if entry is None:
        return {"code": _code_or_unknown(code),
                "message": "Additional processing information is available.",
                "action": "Review the job history.", "severity": "WARNING",
                "retryable": None}
    return {"code": entry.code, "message": entry.message,
            "action": entry.action, "severity": entry.severity,
            "retryable": entry.retryable}

def safe_details(*, missing_fields=(), invalid_fields=(), retry_at_ms=None,
                 attempt=None, max_attempts=None, cause_reason_code=None) -> dict:
    """Build bounded history facts; never accept raw values or exception text.

    Field names identify schema locations, not missing episode coverage.
    Counters describe observations, not retry policy. Cause codes must be known.
    """
    details = {}
    for key, values in (("missing_fields", missing_fields),
                        ("invalid_fields", invalid_fields)):
        if type(values) not in (list, tuple) or len(values) > 20:
            raise ValueError("invalid diagnostic field list")
        if any(type(name) is not str or name not in _FIELDS for name in values):
            raise ValueError("invalid diagnostic field")
        if values:
            details[key] = sorted(set(values))
    for key, value in (("retry_at_ms", retry_at_ms), ("attempt", attempt),
                       ("max_attempts", max_attempts)):
        if value is not None:
            if type(value) is not int or not 0 <= value <= _MAX_INTEGER:
                raise ValueError("invalid diagnostic integer")
            details[key] = value
    if cause_reason_code is not None:
        cause = get_reason(cause_reason_code)
        if cause is None:
            raise ValueError("unregistered cause reason")
        details["cause_reason_code"] = cause.code
    return details

