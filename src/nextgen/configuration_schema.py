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

CONFIGURATION_VERSION = 7
MAX_REVISION = (1 << 63) - 1
MAX_BYTES = 65536


class ConfigurationError(ValueError):
    reason_code = "CONFIGURATION_INVALID"

    def __init__(self):
        super().__init__("Configuration is invalid.")


class ConfigurationEpisodeSelectionError(ConfigurationError):
    reason_code = "TRIAL_COUNTS_INVALID"

    def __init__(self):
        ValueError.__init__(self, "Set backfill or episodes starting with the received episode to at least 1.")


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
    label: str = ""
    help_text: str = ""


# Register new fields with their actual component; do not expose speculative
# provider/acquisition controls before those components define their semantics.
FIELDS = MappingProxyType({
    "torrent_metadata.base_url": FieldDefinition("", "metadata_source", "next_operation",
        label="Torrent metadata source", help_text="Trusted HTTP(S) base folder serving lowercase-infohash.torrent files. No credentials, query, redirects or webhook URLs. Required before acquisition."),
    "torrent_metadata.timeout_seconds": FieldDefinition(30, "integer", "next_operation", minimum=1, maximum=60,
        label="Torrent metadata timeout", help_text="Connect/read timeout and deadline checks between response chunks, in seconds."),
    "qbittorrent.base_url": FieldDefinition("", "download_endpoint", "next_operation",
        label="qBittorrent address", help_text="HTTP or HTTPS server address without credentials, query or subpath. Required before download work."),
    "qbittorrent.category": FieldDefinition("anime-discovery", "download_category", "next_operation",
        label="Download category", help_text="Category label for newly submitted torrents. A label is not proof of ownership."),
    "qbittorrent.timeout_seconds": FieldDefinition(30, "integer", "next_operation", minimum=1, maximum=60,
        label="Download client timeout", help_text="Maximum seconds for a client request."),
    "acquisition.max_episode_mb": FieldDefinition(600, "integer", "next_operation", minimum=1, maximum=1000000,
        label="Maximum video size (MB)", help_text="Hard limit for each selected video. Decimal MB. New selection-plan budgets only."),
    "acquisition.max_plan_mb": FieldDefinition(3000, "integer", "next_operation", minimum=1, maximum=1000000,
        label="Maximum selection-plan size (MB)", help_text="Combined hard limit for prepared selected videos, counting each episode once. Decimal MB. New budgets only."),
    "storage.download_root": FieldDefinition("", "directory", "next_operation",
        label="Download working folder", help_text="Absolute client working folder, separate from published video folders. Required before submission."),
    "trial.backfill_count": FieldDefinition(6, "integer", "next_operation", minimum=0, maximum=1000,
        label="Backfill first episodes", help_text="First X episodes of the verified season. Zero disables backfill; the other count must then be at least 1. New selection plans only."),
    "trial.following_count": FieldDefinition(1, "integer", "next_operation", minimum=0, maximum=1000,
        label="Episodes starting with the received episode", help_text="Includes the triggering episode: 1 keeps only that episode; 2 includes the next. Zero disables this window; backfill must then be at least 1. New selection plans only."),
    "anidb.client_name": FieldDefinition("", "client_name", "next_operation",
        label="AniDB client name", help_text="Registered AniDB HTTP client name. Required before identity work can start."),
    "anidb.client_version": FieldDefinition(1, "integer", "next_operation", minimum=1, maximum=999999,
        label="AniDB client version", help_text="Version registered for the AniDB HTTP client."),
    "providers.timeout_seconds": FieldDefinition(30, "integer", "next_operation", minimum=1, maximum=60,
        label="Provider request timeout", help_text="Maximum time in seconds for one provider request."),
    "logging.level": FieldDefinition("INFO", "level", "next_operation"),
    "logging.components": FieldDefinition(MappingProxyType({}), "levels", "next_operation"),
    "api.host": FieldDefinition("127.0.0.1", "host", "restart", ("api",)),
    "api.port": FieldDefinition(8765, "integer", "restart", ("api",), 1, 65535),
    "worker.concurrency": FieldDefinition(4, "integer", "restart", ("worker",), 1, 32),
    "storage.trial_root": FieldDefinition("", "directory", "next_operation",
        label="Staging folder", help_text="Absolute destination for verified videos staged for viewing before Keep or Reject. Leave blank until configured. Existing files are not moved."),
    "storage.keep_root": FieldDefinition("", "directory", "next_operation",
        label="Keep video folder", help_text="Absolute permanent destination for approved Keep videos. Must agree with the library import target when Sonarr is used."),
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
                   "minimum": spec.minimum, "maximum": spec.maximum,
                   "label": spec.label or path, "help": spec.help_text}
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
            elif spec.kind == "metadata_source":
                if type(item) is not str:raise ConfigurationError()
                if item:
                    from src.nextgen.acquisition.metainfo_source import source_url
                    try:source_url(item)
                    except ValueError:raise ConfigurationError() from None
            elif spec.kind == "download_endpoint":
                if type(item) is not str:raise ConfigurationError()
                if item:
                    from src.nextgen.acquisition.settings import endpoint
                    try:endpoint(item)
                    except ValueError:raise ConfigurationError() from None
            elif spec.kind == "download_category":
                if type(item) is not str or not re.fullmatch('[A-Za-z0-9_-]{1,64}',item):raise ConfigurationError()
            elif spec.kind == "client_name":
                if type(item) is not str or (item and not re.fullmatch(r"[A-Za-z0-9_-]{3,32}",item)):
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
            elif spec.kind == "directory":
                if type(item) is not str:
                    raise ConfigurationError()
                if item and (not PurePosixPath(item).is_absolute() or item.startswith("//")
                        or item == "/" or str(PurePosixPath(item)) != item
                        or any(part in (".", "..") for part in item.split("/"))
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
    roots = [PurePosixPath(result["storage"][key]) for key in ("trial_root", "keep_root", "download_root")
             if result["storage"][key]]
    if any(a.is_relative_to(b) or b.is_relative_to(a) for i,a in enumerate(roots) for b in roots[i+1:]):
        raise ConfigurationError()
    database = PurePosixPath(result["storage"]["database_path"])
    if any(database.is_relative_to(root) for root in roots):
        raise ConfigurationError()
    if result["trial"]["backfill_count"] == 0 and result["trial"]["following_count"] == 0:
        raise ConfigurationEpisodeSelectionError()
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
            _v1_values(document)
        except (ValueError, TypeError):
            raise ConfigurationError() from None
        return 0
    version = document["schema_version"]
    if type(version) is not int or not 1 <= version <= CONFIGURATION_VERSION:
        raise ConfigurationError()
    return version


def _v1_values(values):
    """Validate the published v1 shape without accepting current names there.

    Round-trip through current validation so all unchanged bounds stay strict,
    then restore historical names. The original v0→v1 output remains v1-shaped.
    """
    if type(values) is not dict or "worker" in values:
        raise ConfigurationError()
    current = copy.deepcopy(values)
    if "coordinator" in current:
        current["worker"] = current.pop("coordinator")
    logging_values = current.get("logging", {})
    if type(logging_values) is not dict:
        raise ConfigurationError()
    components = logging_values.get("components", {})
    if type(components) is not dict or "worker" in components:
        raise ConfigurationError()
    if "coordinator" in components:
        components["worker"] = components.pop("coordinator")
    historical = _v2_values(current)
    historical["coordinator"] = historical.pop("worker")
    levels = historical["logging"]["components"]
    if "worker" in levels:
        levels["coordinator"] = levels.pop("worker")
    return historical


def _v0_to_v1(document):
    return {"schema_version": 1, "revision": 1, "settings": _v1_values(document)}


def _v1_to_v2(document):
    if (type(document) is not dict
            or set(document) != {"schema_version", "revision", "settings"}
            or document["schema_version"] != 1):
        raise ConfigurationError()
    current_revision = revision(document["revision"])
    if current_revision == MAX_REVISION:
        raise ConfigurationError()
    values = _v1_values(document["settings"])
    values["worker"] = values.pop("coordinator")
    levels = values["logging"]["components"]
    if "coordinator" in levels:
        levels["worker"] = levels.pop("coordinator")
    return {"schema_version": 2, "revision": current_revision + 1, "settings": values}


def _v2_values(values):
    """Freeze published v2 keys/defaults; additions belong only to v3."""
    if type(values) is not dict:
        raise ConfigurationError()
    storage = values.get("storage", {})
    if type(storage) is not dict or set(storage) & {"trial_root", "keep_root"}:
        raise ConfigurationError()
    historical = _v3_values(values)
    del historical["storage"]["trial_root"]
    del historical["storage"]["keep_root"]
    return historical


def _v2_to_v3(document):
    if (type(document) is not dict
            or set(document) != {"schema_version", "revision", "settings"}
            or document["schema_version"] != 2):
        raise ConfigurationError()
    current_revision = revision(document["revision"])
    if current_revision == MAX_REVISION:
        raise ConfigurationError()
    return {"schema_version": 3, "revision": current_revision + 1,
            "settings": _v3_values(_v2_values(document["settings"]))}


def _v3_values(values):
    """Validate published v3 without adding or accepting v4 provider sections."""
    if type(values) is not dict or set(values) & {"anidb", "providers"}:
        raise ConfigurationError()
    historical = _v4_values(values)
    del historical["anidb"]
    del historical["providers"]
    return historical


def _v3_to_v4(document):
    if (type(document) is not dict or set(document)!={"schema_version","revision","settings"}
            or document["schema_version"]!=3):
        raise ConfigurationError()
    current = revision(document["revision"])
    if current == MAX_REVISION: raise ConfigurationError()
    return {"schema_version":4,"revision":current+1,"settings":_v4_values(_v3_values(document["settings"]))}


def _v4_values(values):
    """Keep published v4 output free of new trial settings."""
    if type(values) is not dict or "trial" in values: raise ConfigurationError()
    historical=_v5_values(values)
    del historical["trial"]
    return historical


def _v4_to_v5(document):
    if (type(document) is not dict or set(document)!={"schema_version","revision","settings"}
            or document["schema_version"]!=4): raise ConfigurationError()
    current=revision(document["revision"])
    if current==MAX_REVISION: raise ConfigurationError()
    return {"schema_version":5,"revision":current+1,"settings":_v5_values(_v4_values(document["settings"]))}


def _v5_values(values):
    """Published v5 has no client/size settings or download_root."""
    if type(values) is not dict or set(values) & {'qbittorrent','acquisition'}:raise ConfigurationError()
    storage=values.get('storage',{})
    if type(storage) is not dict or 'download_root' in storage:raise ConfigurationError()
    historical=_v6_values(values)
    del historical['qbittorrent']
    del historical['acquisition']
    del historical['storage']['download_root']
    return historical


def _v5_to_v6(document):
    if (type(document) is not dict or set(document)!={'schema_version','revision','settings'}
            or document['schema_version']!=5):raise ConfigurationError()
    current=revision(document['revision'])
    if current==MAX_REVISION:raise ConfigurationError()
    return {'schema_version':6,'revision':current+1,'settings':_v6_values(_v5_values(document['settings']))}


def _v6_values(values):
    """Keep published v6 shapes free of metadata-source fields."""
    if type(values) is not dict or 'torrent_metadata' in values:raise ConfigurationError()
    historical=validate_values(values)
    del historical['torrent_metadata']
    return historical


def _v6_to_v7(document):
    if (type(document) is not dict or set(document)!={'schema_version','revision','settings'}
            or document['schema_version']!=6):raise ConfigurationError()
    current=revision(document['revision'])
    if current==MAX_REVISION:raise ConfigurationError()
    return {'schema_version':7,'revision':current+1,'settings':validate_values(_v6_values(document['settings']))}


# Explicit ordered conversion steps; future renames/type conversions go in a
# new step. Do not infer renames, silently drop keys, or rewrite old converters.
CONVERSIONS = MappingProxyType({0: _v0_to_v1, 1: _v1_to_v2, 2: _v2_to_v3, 3: _v3_to_v4, 4: _v4_to_v5, 5: _v5_to_v6, 6: _v6_to_v7})


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
    # Desired values were validated together, but pinning startup-only fields
    # creates a different combination. Recheck cross-field constraints before
    # exposing it (for example media roots versus the still-active database).
    effective = validate_values(effective)
    return OperationConfiguration(latest.revision, startup.revision, component,
                                  _freeze(effective), tuple(pending))
