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
    Reason('API_AUTH_REQUIRED', 'Request credentials are missing, invalid or conflicting.', 'Authentication is required.', 'Use the credential required for this API route.', 'WARNING', False),
    Reason('API_AUTH_UNCONFIGURED', 'Required route-specific access credentials are not configured.', 'API access has not been configured.', 'Initialize the separate management and webhook access keys locally.', 'WARNING', False),
    Reason('API_CSRF_REQUIRED', 'A browser mutation lacks the session-bound anti-forgery token.', 'This browser request could not be verified.', 'Refresh your session and try again.', 'WARNING', False),
    Reason('API_ORIGIN_INVALID', 'Request origin or host differs from the configured application origin.', 'This request came from an unexpected address.', 'Use the configured dashboard address.', 'WARNING', False),
    Reason('API_REQUEST_INVALID', 'Request framing, JSON structure, fields or pagination failed validation.', 'The API request is invalid.', 'Review the required request fields.', 'WARNING', False),
    Reason('API_WEBHOOK_INVALID', 'Release name or supported v1 hash is missing, ambiguous or invalid.', 'The incoming release details are incomplete or invalid.', 'Send a release name and matching 40-character torrent hash.', 'WARNING', False),
    Reason('API_BODY_TOO_LARGE', 'The request exceeds the bounded body size.', 'The request is too large.', 'Send a smaller request.', 'WARNING', False),
    Reason('API_MEDIA_TYPE_INVALID', 'Unsupported request content type or encoding.', 'This request format is not supported.', 'Send UTF-8 JSON.', 'WARNING', False),
    Reason('API_ROUTE_NOT_FOUND', 'No versioned route or requested resource exists.', 'The requested API resource was not found.', 'Check the API address and resource identifier.', 'INFO', False),
    Reason('API_METHOD_INVALID', 'The HTTP method is not supported by this route.', 'This action is not supported at this address.', 'Use the documented API method.', 'WARNING', False),
    Reason('API_RATE_LIMITED', 'A bounded authentication or session limit was reached.', 'Too many requests; try again shortly.', 'Wait before trying again.', 'WARNING', None),
    Reason('API_UNAVAILABLE', 'An API operation failed without safely exposing internal error text.', 'The API is temporarily unavailable.', 'Check service status and try again later.', 'ERROR', None),
    Reason('JOB_CANCELED', 'An operator explicitly canceled unfinished work.', 'This work was canceled.', 'Check cleanup status for any remaining downloads.', 'INFO', False),
    Reason('CANCELLATION_DRAINING', 'Cancellation is durable; active operation handlers must drain before cleanup.', 'Waiting for active work to stop before cleanup.', 'Wait for the current work to finish stopping.', 'INFO', None),
    Reason('CANCELLATION_PENDING', 'Cleanup is incomplete; external outcomes are reconciled without repeating uncertain commands.', 'Cancellation cleanup is waiting for confirmation.', 'Check the existing torrent and cleanup status.', 'INFO', None),
    Reason('CANCELLATION_REVIEW', 'Cleanup ownership, file identity, sharing or external outcome cannot be established safely.', 'Cancellation cleanup needs attention.', 'Review the preserved torrent or files before further cleanup.', 'WARNING', False),
    Reason('CANCELLATION_COMPLETE', 'Owned-resource and registered temporary-file cleanup completed or no resources existed.', 'Cancellation cleanup is complete.', 'No further cleanup is required for the recorded resources.', 'INFO', None),
    Reason('TORRENT_SELECTION_UNCERTAIN', 'Fixed file selection was authorized once; confirmation is pending.', 'Video file selection is waiting for confirmation.', 'Inspect the existing selection; do not repeat uncertain commands automatically.', 'INFO', None),
    Reason('TORRENT_SELECTION_CONFIRMED', 'Exact selected-video and skipped-sidecar priorities were observed while stopped.', 'The video file is selected and ready to download.', 'Continue with the recorded download start.', 'INFO', None),
    Reason('TORRENT_START_UNCERTAIN', 'A single durable start authorization exists; stopped or checking observations cannot rearm it.', 'Download startup is waiting for confirmation.', 'Inspect the existing download; do not restart it automatically.', 'INFO', None),
    Reason('TORRENT_DOWNLOAD_IN_PROGRESS', 'The client reports active transfer with exact selection and ownership.', 'The selected video is downloading.', 'Wait for the download to finish.', 'INFO', None),
    Reason('TORRENT_DOWNLOAD_COMPLETE', 'The client reports selected-file progress of one with matching provenance.', 'The download client reports that the selected video is complete.', 'Verify the local video before making it available.', 'INFO', None),
    Reason('TORRENT_DOWNLOAD_WAITING', 'The owned torrent is absent from a current authoritative inventory observation.', 'Waiting for the existing download to appear.', 'Check the download client; do not add another torrent automatically.', 'INFO', None),
    Reason('TORRENT_TRANSFER_CONFLICT', 'Transfer ownership, priorities, piece geometry, state or immutable evidence contradicts the journal.', 'Download details changed and need review.', 'Review ownership, selected files and the existing download before continuing.', 'WARNING', False),
    Reason('TORRENT_PIECE_OVERLAP', 'Selected video shares boundary pieces with unwanted file bytes; zero-overlap policy blocks start.', 'This video shares download pieces with files that are not selected.', 'Review the torrent layout or choose a source containing only the video.', 'WARNING', False),
    Reason('TORRENT_SNAPSHOT_CHANGED', 'Client state changed during inspection or is temporarily checking or moving.', 'The download is changing or being checked.', 'Wait for a stable status check.', 'INFO', None),
    Reason("IDENTITY_INCOMPLETE", "Required provider-verified identity facts are missing.",
           "Anime identification is incomplete.", "Review the missing identification details.",
           "WARNING", None),
    Reason("IDENTITY_INVALID", "The resolved identity failed AnimeSeries validation.",
           "Anime identification could not be verified.", "Review the identification results.",
           "WARNING", False),
    Reason("IDENTITY_CONFLICT", "Verified identifiers conflict with stored identity.",
           "Conflicting anime information needs review.", "Review the conflicting identifiers.",
           "WARNING", False),
    Reason("DOWNLOAD_CLIENT_UNAVAILABLE", "A bounded client request failed; submission outcome may require reconciliation.",
           "The download client could not be reached safely.", "Check client availability; preserve any pending submission intent.", "WARNING", None),
    Reason("DOWNLOAD_CLIENT_RESPONSE_INVALID", "Client response shape or provenance observation failed validation.",
           "The download client returned information that needs review.", "Review client compatibility and recorded source evidence.", "WARNING", False),
    Reason("DOWNLOAD_CLIENT_AUTH_FAILED", "The configured client did not accept session authentication.",
           "The download client rejected authentication.", "Review private client credentials and access settings.", "WARNING", False),
    Reason("DOWNLOAD_CLIENT_UNSUPPORTED", "The client version is outside the explicit supported API family.",
           "This download client version is not supported.", "Review supported client versions before retrying.", "WARNING", False),
    Reason("TORRENT_SUBMISSION_UNCERTAIN", "A durable one-shot intent cannot yet be confirmed; never replay its add.",
           "The torrent submission is waiting for confirmation.", "Check the existing submission; do not add it again automatically.", "INFO", None),
    Reason("TORRENT_ALREADY_PRESENT", "Exact-hash inventory existed before this application's send authorization.",
           "This torrent already exists in the download client.", "Review who owns it before taking any action.", "WARNING", False),
    Reason("TORRENT_PROVENANCE_CONFLICT", "Observed marker, destination, category, management, state or files contradict the saved intent.",
           "Torrent ownership or file details need review.", "Compare the existing torrent with the saved submission intent.", "WARNING", False),
    Reason("TORRENT_STOPPED_CONFIRMED", "Saved intent matches authoritative stopped torrent provenance and file inventory.",
           "The submitted torrent is confirmed and stopped.", "Apply approved file selection before starting any download.", "INFO", None),
    Reason("DOWNLOAD_CONFIGURATION_INVALID", "Download endpoint, local folder or credentials are incomplete or invalid.",
           "Configure the download client and download folder before acquisition.", "Review download settings and private credentials.", "WARNING", False),
    Reason("ACQUISITION_SIZE_LIMIT", "A selected video or combined prepared-video budget exceeds its frozen hard limit.",
           "The selected video exceeds the episode or selection-plan size limit.", "Review video sizes and the recorded plan budget.", "WARNING", False),
    Reason("ACQUISITION_SIZE_EVIDENCE_MISSING", "A prior prepared plan lacks independently recorded selected-byte evidence.",
           "An existing acquisition plan needs its file size reviewed.", "Reinspect the existing source before adding more work to this plan.", "WARNING", False),
    Reason("ACQUISITION_SOURCE_MISSING", "A normalized v1 torrent identity is absent or unsupported.",
           "A supported torrent identity is required before acquisition.", "Check the incoming release source.", "WARNING", False),
    Reason("ACQUISITION_METADATA_INVALID", "Hash-bound metadata or its single-file declaration could not be validated.",
           "The torrent file list could not be verified.", "Review the source and declared episode before proceeding.", "WARNING", False),
    Reason("ACQUISITION_PLAN_CONFLICT", "Reservation, source or immutable preparation facts changed.",
           "Acquisition details changed and need review.", "Review the recorded episode reservation and source.", "WARNING", False),
    Reason("ACQUISITION_PLAN_READY", "Hash-bound single-video metadata and a stable submission marker were recorded.",
           "Source files have been inspected and the acquisition plan is ready.", "Complete download policy and client setup before submission.", "INFO", None),
    Reason("EPISODE_RESERVATION_GRANTED", "A selected verified episode has an exclusive durable reservation.",
           "This episode is reserved for acquisition.", "Continue with source verification before starting a download.", "INFO", None),
    Reason("EPISODE_RESERVED", "Another job owns the exact verified episode reservation.",
           "Another job has reserved this episode.", "Review the existing reservation before resuming this job.", "INFO", None),
    Reason("EPISODE_RESERVATION_CONFLICT", "Episode evidence, selection or reservation identity is inconsistent.",
           "Episode reservation details need review.", "Check the episode identity and recorded reservation.", "WARNING", False),
    Reason("TRIAL_SELECTED", "The verified received episode falls within its immutable trial window.",
           "This episode is selected for the trial.", "Continue only after acquisition prerequisites are verified.", "INFO", None),
    Reason("TRIAL_OUTSIDE_WINDOW", "The received episode is outside the recorded trial windows.",
           "This episode is outside the trial selection.", "Review the recorded trial window if a different selection is needed.", "INFO", False),
    Reason("TRIAL_DISABLED", "Both counts are zero and no prior trial plan exists.",
           "Trial episode selection is disabled.", "Set a backfill or following count to create new trial plans.", "INFO", False),
    Reason("TRIAL_PLAN_CONFLICT", "The source verification or trial plan is inconsistent.",
           "The trial plan needs review.", "Review the verified episode and recorded trial plan.", "WARNING", False),
    Reason("RELEASE_UNRESOLVED", "A release has missing, ambiguous or unsupported declared episode evidence.",
           "The release's episode coverage needs review.", "Review the declared episode and exact release-file evidence before continuing.", "WARNING", False),
    Reason("RELEASE_CONFLICT", "Release mapping, episode ownership or persisted source evidence conflicts.",
           "Release episode information conflicts.", "Review the episode identifiers and mapping evidence.", "WARNING", False),
    Reason("PROVIDER_UNAVAILABLE", "A provider request could not complete due to availability.",
           "An information provider is temporarily unavailable.", "The operation can be retried.",
           "WARNING", True),
    Reason("PROVIDER_CONFIGURATION_INVALID", "Required AniDB client or TVDB API-key configuration is missing or invalid.",
           "Provider configuration is incomplete or invalid.", "Configure the registered AniDB client and TVDB API key before starting identity work.", "ERROR", False),
    Reason("SECRET_STORAGE_UNAVAILABLE", "The private credential file could not be read or published safely.",
           "Credentials could not be accessed safely.", "Review credential storage, permissions and file format.", "ERROR", None),
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
    Reason("TRIAL_COUNTS_INVALID", "Both episode selection counts are zero.",
           "Set backfill or episodes starting with the received episode to at least 1.",
           "Increase at least one of the two episode counts.", "WARNING", False),
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

