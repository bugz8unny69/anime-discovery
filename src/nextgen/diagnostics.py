"""Safe structured NextGen diagnostics; journal output is separate from SQLite history."""
import logging
import re
import time

from src.nextgen.settings import Settings

TRACE = 5
logging.addLevelName(TRACE, "TRACE")
_ALLOWED = frozenset({"component", "event_id", "job_id", "attempt", "reason_code",
                      "error_type", "retryable", "elapsed_ms", "operation", "outcome"})
_TOKEN = re.compile(r"^[a-zA-Z0-9_.:-]{1,96}$")
_SECRETS = (
    (re.compile(r"(?i)\\b(bearer)\\s+[^\\s,;\\]\\)]+"), r"\\1 [REDACTED]"),
    (re.compile(r"(?i)\\b(password|passkey|access[_-]?token|token|api[_-]?key|apikey|secret|cookie|authorization)\\b\\s*[:=]\\s*[^\\s,;\\]\\)]+"), r"\\1=[REDACTED]"),
    (re.compile(r"(?i)(https?://)[^/@\\s]+@"), r"\\1[REDACTED]@"),
    (re.compile(r"(?i)([?&](?:token|key|api_key|passkey|password|secret|auth|signature)=)[^&#\\s]+"), r"\\1[REDACTED]"),
)

def redact(value) -> str:
    output = str(value)
    for pattern, replacement in _SECRETS:
        output = pattern.sub(replacement, output)
    return output

class SafeFormatter(logging.Formatter):
    def format(self, record):
        return redact(super().format(record))

def configure_logging(settings: Settings, component: str, *, logger=None):
    """Apply validated settings without installing duplicate handlers."""
    target = logger if logger is not None else logging.getLogger("nextgen." + component)
    if not target.handlers:
        target.addHandler(logging.StreamHandler())
    target.setLevel(TRACE if settings.logging.level_for(component) == "TRACE"
                    else logging._nameToLevel[settings.logging.level_for(component)])
    target.propagate = False
    for handler in target.handlers:
        handler.setFormatter(SafeFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"))
    return target

def event(logger, level, name: str, **fields):
    """Log bounded correlation metadata, never release bodies or arbitrary payloads."""
    if not _TOKEN.fullmatch(name):
        raise ValueError("invalid event name")
    parts = ["event=" + name]
    for key, value in fields.items():
        if key not in _ALLOWED or value is None:
            continue
        if key in ("job_id", "event_id", "attempt", "elapsed_ms"):
            if type(value) is not int or value < 0:
                continue
            safe = str(value)
        elif key == "retryable":
            if type(value) is not bool:
                continue
            safe = str(value).lower()
        else:
            if not isinstance(value, str) or not _TOKEN.fullmatch(value):
                continue
            safe = value
        parts.append(key + "=" + safe)
    logger.log(level, " ".join(parts))

class Span:
    def __init__(self):
        self.started = time.monotonic()

    def milliseconds(self):
        return max(0, int((time.monotonic() - self.started) * 1000))
