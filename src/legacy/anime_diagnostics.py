"""Safe, SQLite-independent operational diagnostics for systemd journal.

Only allowlisted correlation fields are emitted. Exception tracebacks are
formatted at the catching boundary and redacted before reaching handlers.
"""
import logging
import re
import time

_FIELDS = frozenset({
    "subsystem", "stage", "operation", "outcome", "job_id",
    "notification_id", "attempt", "tvdb_id", "season", "episode",
    "torrent_hash", "checkpoint", "error_code", "error_type",
    "retryable", "elapsed_ms",
})
_TOKEN = re.compile(r"^[a-zA-Z0-9_.:-]{1,96}$")
_SECRETS = (
    (re.compile(r"(?i)\b(bearer)\s+[^\s,;\]\)]+"), r"\1 [REDACTED]"),
    (re.compile(r"(?i)\b(password|passkey|access[_-]?token|token|api[_-]?key|apikey|x-emby-token|secret|cookie|authorization|signature)\b"
                r"(\s*[:=]\s*|\s+)[^\s,;\]\)]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(https?://)[^/@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)([?&](?:token|access_token|key|api_key|apikey|passkey|password|secret|auth|signature|x-emby-token)=)[^&#\s]+"),
     r"\1[REDACTED]"),
)

def redact(message):
    result = str(message)
    for pattern, replacement in _SECRETS:
        result = pattern.sub(replacement, result)
    return result

class SafeFormatter(logging.Formatter):
    """Redact both record messages and exception tracebacks."""
    def format(self, record):
        return redact(super().format(record))

def configure_logging(level=logging.INFO):
    """Install redaction on existing stream handlers; do not add duplicates."""
    root = logging.getLogger()
    if not root.handlers:
        root.addHandler(logging.StreamHandler())
    root.setLevel(level)
    for handler in root.handlers:
        handler.setFormatter(SafeFormatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
    return root

def _safe_value(key, value):
    if value is None:
        return None
    if key in ("job_id", "notification_id", "attempt", "tvdb_id",
               "season", "episode", "elapsed_ms"):
        if type(value) is not int or value < 0:
            return None
        return str(value)
    if key == "retryable":
        return "true" if value is True else "false" if value is False else None
    if key == "torrent_hash":
        if not isinstance(value, str) or not re.fullmatch(r"[a-fA-F0-9]{40,64}", value):
            return None
        return value[:12].lower()
    if not isinstance(value, str) or not _TOKEN.fullmatch(value):
        return None
    return value

def event(logger, level, name, *, exc_info=False, **fields):
    """Emit bounded structured evidence, never raw payloads or URLs.

    Call with exc_info=True *inside* an except block. Known failures may
    legitimately use WARNING without a traceback; unexpected ones use ERROR.
    """
    if not _TOKEN.fullmatch(name):
        raise ValueError("Invalid diagnostic event")
    detail = ["event=" + name]
    for key, value in fields.items():
        if key not in _FIELDS:
            continue
        safe = _safe_value(key, value)
        if safe is not None:
            detail.append(key + "=" + safe)
    logger.log(level, " ".join(detail), exc_info=exc_info)

class Span:
    """Monotonic clock for operation timings; no external dependencies."""
    def __init__(self):
        self.started = time.monotonic()

    def milliseconds(self):
        return max(0, int((time.monotonic() - self.started) * 1000))
