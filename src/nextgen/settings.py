"""Validated, intentionally small NextGen configuration (no legacy dependencies)."""
from dataclasses import dataclass, field
from pathlib import Path
import json

LEVELS = frozenset({"TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"})
COMPONENTS = frozenset({"supervisor", "intake", "coordinator", "identity", "acquisition"})

@dataclass(frozen=True)
class LoggingSettings:
    level: str = "INFO"
    components: dict[str, str] = field(default_factory=dict)

    def __post_init__(self):
        if self.level not in LEVELS:
            raise ValueError("invalid logging.level")
        if not isinstance(self.components, dict):
            raise ValueError("logging.components must be an object")
        for name, level in self.components.items():
            if name not in COMPONENTS or level not in LEVELS:
                raise ValueError("invalid component logging level")

    def level_for(self, component: str) -> str:
        return self.components.get(component, self.level)

@dataclass(frozen=True)
class Settings:
    logging: LoggingSettings = field(default_factory=LoggingSettings)

def parse_settings(value: dict) -> Settings:
    if not isinstance(value, dict) or set(value) - {"logging"}:
        raise ValueError("unknown settings section")
    logging_data = value.get("logging", {})
    if not isinstance(logging_data, dict) or set(logging_data) - {"level", "components"}:
        raise ValueError("invalid logging section")
    return Settings(logging=LoggingSettings(**logging_data))

def load_settings(path: str | Path) -> Settings:
    """Read explicit JSON configuration; missing files/errors fail loudly."""
    return parse_settings(json.loads(Path(path).read_text(encoding="utf-8")))
