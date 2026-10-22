"""Bounded structured diagnostics for all NextGen processes.

Never pass arbitrary user/provider payloads to logging. Runtime output is
best-effort; SQLite event/job history must be committed with job transitions.
"""
import logging
import re
import time
import traceback

from src.nextgen.settings import Settings

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
_LEVELS = {"TRACE": TRACE, "DEBUG": logging.DEBUG, "INFO": logging.INFO,
           "WARNING": logging.WARNING, "ERROR": logging.ERROR,
           "CRITICAL": logging.CRITICAL}
_ALLOWED = frozenset({"component", "event_id", "job_id", "trace_id", "attempt",
                      "reason_code", "error_type", "retryable", "elapsed_ms",
                      "operation", "outcome"})
_TOKEN = re.compile(r"^[a-zA-Z0-9_.:-]{1,96}$")
_SECRETS = (
    (re.compile(r"(?i)\bBearer\s+[^\s,;]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(password|passkey|access[_-]?token|token|api[_-]?key|apikey|secret|cookie|authorization)\b\s*[:=]\s*[^\s,;]+"), r"\1=[REDACTED]"),
    (re.compile(r"(?i)(https?://)[^/@\s]+@"), r"\1[REDACTED]@"),
    (re.compile(r"(?i)([?&](?:token|key|api_key|passkey|password|secret|auth|signature)=)[^&#\s]+"), r"\1[REDACTED]"),
)

def redact(value) -> str:
    result = str(value)
    for pattern, replacement in _SECRETS:
        result = pattern.sub(replacement, result)
    return result

class SafeFormatter(logging.Formatter):
    def format(self, record):
        # Format exception and traceback before redacting the complete output.
        return redact(super().format(record))

def configure_logging(settings: Settings, component: str, *, logger=None):
    """Set/reload this process logger, without duplicate handlers."""
    if component not in {"supervisor", "intake", "coordinator", "identity", "acquisition"}:
        raise ValueError("unsupported logging component")
    target = logger if logger is not None else logging.getLogger("nextgen." + component)
    if not target.handlers:
        target.addHandler(logging.StreamHandler())
    target.setLevel(_LEVELS[settings.logging.level_for(component)])
    target.propagate = False
    for handler in target.handlers:
        handler.setFormatter(SafeFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    return target

def event(logger, level, name: str, **fields):
    """Allowlisted machine-readable fields; raw webhook/provider values prohibited."""
    if not isinstance(name, str) or not _TOKEN.fullmatch(name):
        raise ValueError("invalid event name")
    if not logger.isEnabledFor(level):
        return
    parts = ["event=" + name]
    for key, value in fields.items():
        if key not in _ALLOWED or value is None:
            continue
        if key in ("event_id", "job_id", "attempt", "elapsed_ms"):
            if type(value) is not int or value < 0:
                continue
            safe = str(value)
        elif key == "retryable":
            if type(value) is not bool:
                continue
            safe = str(value).lower()
        else:
            if type(value) is not str or not _TOKEN.fullmatch(value):
                continue
            safe = value
        parts.append(key + "=" + safe)
    logger.log(level, " ".join(parts))

def exception(logger, name: str, exc: Exception, *, level=logging.ERROR, **fields):
    """Log bounded error context and sanitized exception traceback.

    Use only at a catch boundary. Never attach arbitrary extra payloads.
    """
    if not logger.isEnabledFor(level):
        return
    fields["error_type"] = type(exc).__name__
    event(logger, level, name, **fields)
    # A real traceback can include file paths / exception text; formatter redacts
    # known secrets. Do not log locals or full incoming requests.
    logger.log(level, "exception=%s", type(exc).__name__,
               exc_info=(type(exc), exc, exc.__traceback__))

class Span:
    def __init__(self):
        self.started = time.monotonic()

    def milliseconds(self):
        return max(0, int((time.monotonic() - self.started) * 1000))
