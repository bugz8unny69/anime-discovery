"""Pure, versioned configuration validation/conversion and operation snapshots.

Configuration version, publication revision, SQLite version and AnimeSeries
version are independent. No disk, network, logging or legacy imports here.
"""
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from types import MappingProxyType
import copy
import ipaddress
import json
import re

from src.nextgen.settings import COMPONENTS, Settings, parse_settings

CONFIGURATION_VERSION = 1
MAX_REVISION = (1 << 63) - 1
MAX_BYTES = 65536


class ConfigurationError(ValueError):
    reason_code = "CONFIGURATION_INVALID"

    def __init__(self):
        super().__init__("Configuration is invalid.")


class ConfigurationConflict(ConfigurationError):
    reason_code = "CONFIGURATION_CONFLICT"

    def __init__(self):
        ValueError.__init__(self, "Configuration changed; refresh before applying changes.")


class ConfigurationMigrationRequired(ConfigurationError):
    reason_code = "CONFIGURATION_MIGRATION_REQUIRED"

    def __init__(self):
        ValueError.__init__(self, "Configuration requires an explicit version upgrade.")


class ConfigurationIOError(OSError):
    reason_code = "CONFIGURATION_STORAGE_FAILED"

    def __init__(self):
        super().__init__("Configuration storage could not be accessed safely.")


@dataclass(frozen=True)
class FieldDefinition:
    default: object
    kind: str
    apply_mode: str
    restart_components: tuple[str, ...] = ()
    minimum: int | None = None
    maximum: int | None = None


# Register new fields with their actual component; do not expose speculative
# provider/acquisition controls before those components define their semantics.
FIELDS = MappingProxyType({
    "logging.level": FieldDefinition("INFO", "level", "next_operation"),
    "logging.components": FieldDefinition(MappingProxyType({}), "levels", "next_operation"),
    "api.host": FieldDefinition("127.0.0.1", "host", "restart", ("api",)),
    "api.port": FieldDefinition(8765, "integer", "restart", ("api",), 1, 65535),
    "coordinator.concurrency": FieldDefinition(4, "integer", "restart", ("coordinator",), 1, 32),
    "storage.database_path": FieldDefinition(
        "/var/lib/anime-discovery/nextgen.sqlite", "path", "restart", tuple(sorted(COMPONENTS))),
})


def revision(value):
    if type(value) is not int or not 1 <= value <= MAX_REVISION:
        raise ConfigurationError()
    return value


def _freeze(value):
    if isinstance(value, Mapping):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    return value


def _plain(value):
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    return value


def defaults():
    result = {}
    for path, spec in FIELDS.items():
        section, name = path.split(".")
        result.setdefault(section, {})[name] = _plain(spec.default)
    return result


def field_definitions():
    """Detached JSON-compatible metadata for the future authenticated API."""
    return {path: {"default": _plain(spec.default), "type": spec.kind,
                   "apply_mode": spec.apply_mode, "restart_components": list(spec.restart_components),
                   "minimum": spec.minimum, "maximum": spec.maximum}
            for path, spec in FIELDS.items()}


def _host(value):
    if (type(value) is not str or not 1 <= len(value) <= 253 or not value.isascii()
            or "%" in value or any(ord(char) <= 32 or ord(char) == 127 for char in value)):
        return False
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return all(re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label)
                   for label in value.split("."))


def validate_values(value):
    if type(value) is not dict:
        raise ConfigurationError()
    result = defaults()
    for section, fields in value.items():
        if type(section) is not str or section not in result or type(fields) is not dict:
            raise ConfigurationError()
        for key, item in fields.items():
            if type(key) is not str or section + "." + key not in FIELDS:
                raise ConfigurationError()
            spec = FIELDS[section + "." + key]
            if spec.kind == "integer":
                if type(item) is not int or not spec.minimum <= item <= spec.maximum:
                    raise ConfigurationError()
            elif spec.kind == "host":
                if not _host(item):
                    raise ConfigurationError()
            elif spec.kind == "path":
                if (type(item) is not str or len(item) > 4096
                        or not PurePosixPath(item).is_absolute()
                        or str(PurePosixPath(item)) == "/"
                        or any(ord(char) < 32 or ord(char) == 127 for char in item)):
                    raise ConfigurationError()
            elif spec.kind == "levels":
                if type(item) is not dict:
                    raise ConfigurationError()
            result[section][key] = copy.deepcopy(item)
    try:
        # Reuse the existing strict component/level validator.
        parse_settings({"logging": result["logging"]})
    except (ValueError, TypeError):
        raise ConfigurationError() from None
    return result


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ConfigurationError()
        result[key] = value
    return result


def _invalid_constant(value):
    raise ConfigurationError()


def decode(raw):
    if type(raw) is not bytes or len(raw) > MAX_BYTES:
        raise ConfigurationError()
    try:
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                          parse_constant=_invalid_constant)
    except (ValueError, UnicodeError, RecursionError):
        raise ConfigurationError() from None


@dataclass(frozen=True)
class ConfigurationSnapshot:
    revision: int
    values: Mapping = field(repr=False)
    schema_version: int = CONFIGURATION_VERSION

    def __post_init__(self):
        revision(self.revision)
        if type(self.schema_version) is not int or self.schema_version != CONFIGURATION_VERSION:
            raise ConfigurationError()
        # Detached, deeply immutable validated values even for direct construction.
        object.__setattr__(self, "values", _freeze(validate_values(_plain(self.values))))

    def value(self, path):
        if type(path) is not str or path not in FIELDS:
            raise ConfigurationError()
        section, key = path.split(".")
        return self.values[section][key]

    def to_document(self):
        return {"schema_version": self.schema_version, "revision": self.revision,
                "settings": _plain(self.values)}

    def logging_settings(self) -> Settings:
        return parse_settings({"logging": _plain(self.values["logging"])})


def document_snapshot(document):
    if (type(document) is not dict
            or set(document) != {"schema_version", "revision", "settings"}):
        raise ConfigurationError()
    return ConfigurationSnapshot(document["revision"], document["settings"], document["schema_version"])


def source_version(document):
    if type(document) is not dict:
        raise ConfigurationError()
    if "schema_version" not in document:
        # v0 means only the previously supported unversioned NextGen logging
        # object. This is deliberately NOT a converter for legacy production.
        if set(document) - {"logging"}:
            raise ConfigurationError()
        try:
            parse_settings(document)
        except (ValueError, TypeError):
            raise ConfigurationError() from None
        return 0
    version = document["schema_version"]
    if type(version) is not int or not 1 <= version <= CONFIGURATION_VERSION:
        raise ConfigurationError()
    return version


def _v0_to_v1(document):
    return {"schema_version": 1, "revision": 1, "settings": validate_values(document)}


# Explicit ordered conversion steps; future renames/type conversions go in a
# new step. Do not infer renames, silently drop keys, or rewrite old converters.
CONVERSIONS = MappingProxyType({0: _v0_to_v1})


def convert_document(document):
    version = source_version(document)
    result = copy.deepcopy(document)
    while version < CONFIGURATION_VERSION:
        converter = CONVERSIONS.get(version)
        if converter is None:
            raise ConfigurationMigrationRequired()
        result = converter(result)
        if type(result) is not dict or result.get("schema_version") != version + 1:
            raise ConfigurationError()
        version += 1
    return document_snapshot(result)


def load_current(raw):
    document = decode(raw)
    if source_version(document) != CONFIGURATION_VERSION:
        raise ConfigurationMigrationRequired()
    return document_snapshot(document)


def encode(snapshot):
    encoded = (json.dumps(snapshot.to_document(), sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_BYTES:
        raise ConfigurationError()
    return encoded


def patch_snapshot(current, changes):
    if type(changes) is not dict or not changes:
        raise ConfigurationError()
    candidate = current.to_document()["settings"]
    for section, values in changes.items():
        if type(section) is not str or section not in candidate or type(values) is not dict:
            raise ConfigurationError()
        for key, value in values.items():
            if type(key) is not str or section + "." + key not in FIELDS:
                raise ConfigurationError()
            candidate[section][key] = copy.deepcopy(value)
    validated = validate_values(candidate)
    changed = tuple(path for path in FIELDS
                    if _plain(current.value(path)) != validated[path.split(".")[0]][path.split(".")[1]])
    if not changed:
        return current, ()
    if current.revision == MAX_REVISION:
        raise ConfigurationError()
    return ConfigurationSnapshot(current.revision + 1, validated), changed


@dataclass(frozen=True)
class OperationConfiguration:
    desired_revision: int
    startup_revision: int
    component: str
    values: Mapping = field(repr=False)
    pending_restart_fields: tuple[str, ...]

    def value(self, path):
        if type(path) is not str or path not in FIELDS:
            raise ConfigurationError()
        section, key = path.split(".")
        return self.values[section][key]

    def logging_settings(self):
        return parse_settings({"logging": _plain(self.values["logging"])})


def for_operation(latest, startup, *, component):
    """Fresh operational values, pinned startup values, no global reload signal."""
    if type(component) is not str or component not in COMPONENTS:
        raise ConfigurationError()
    if latest.revision < startup.revision:
        raise ConfigurationConflict()
    effective = latest.to_document()["settings"]
    pending = []
    for path, spec in FIELDS.items():
        if spec.apply_mode == "restart":
            section, key = path.split(".")
            effective[section][key] = _plain(startup.value(path))
            if component in spec.restart_components and latest.value(path) != startup.value(path):
                pending.append(path)
    return OperationConfiguration(latest.revision, startup.revision, component,
                                  _freeze(effective), tuple(pending))
