"""Service-owned private credential repository; no HTTP, environment fallback or SQL.

Public results contain presence/revision only. Trusted provider code obtains a
credential object explicitly; values never appear in repr, history or logs.
"""
from dataclasses import dataclass
import json
import os
from pathlib import Path
import stat
import uuid

from src.nextgen.configuration import _directory, _writer, _write_bytes
from src.nextgen.configuration_schema import ConfigurationError, ConfigurationConflict, decode, revision
from src.nextgen.providers.errors import ProviderConfigurationError
from src.nextgen.providers.http import Credentials

NAME = "secrets.json"


class SecretStorageError(ConfigurationError):
    reason_code = "SECRET_STORAGE_UNAVAILABLE"
    def __init__(self):
        ValueError.__init__(self,"Provider credentials could not be accessed safely.")


@dataclass(frozen=True)
class CredentialStatus:
    revision: int
    tvdb_api_key_configured: bool


@dataclass(frozen=True)
class SecretUpdateResult:
    status: CredentialStatus
    saved: bool
    durability_confirmed: bool
    reason_code: str | None = None


def _value(value):
    if type(value) is not str: raise SecretStorageError()
    if value:
        try: Credentials(value)
        except ValueError: raise SecretStorageError() from None
        except RuntimeError: raise SecretStorageError() from None
    return value


def _read(fd):
    stream_fd = os.open(NAME,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK|os.O_CLOEXEC,dir_fd=fd)
    with os.fdopen(stream_fd,"rb") as stream:
        metadata = os.fstat(stream.fileno())
        if (not stat.S_ISREG(metadata.st_mode) or metadata.st_uid!=os.geteuid()
                or metadata.st_mode & 0o077 or metadata.st_nlink!=1):
            raise SecretStorageError()
        raw = stream.read(65537)
    try:
        document = decode(raw)
        if (type(document) is not dict or set(document)!={"schema_version","revision","credentials"}
                or type(document["schema_version"]) is not int or document["schema_version"]!=1
                or type(document["credentials"]) is not dict or set(document["credentials"])!={"tvdb_api_key"}):
            raise SecretStorageError()
        return revision(document["revision"]),_value(document["credentials"]["tvdb_api_key"])
    except (ValueError,TypeError,KeyError):
        raise SecretStorageError() from None


def _private_directory(fd):
    metadata = os.fstat(fd)
    if metadata.st_uid!=os.geteuid() or metadata.st_mode & 0o022:
        raise SecretStorageError()


def _publish(fd, current_revision, value):
    name = ".secrets-"+uuid.uuid4().hex+".tmp"
    raw = (json.dumps({"schema_version":1,"revision":current_revision,
                       "credentials":{"tvdb_api_key":value}},sort_keys=True)+"\n").encode()
    try:
        _write_bytes(fd,name,raw)  # Always new service-owned mode 0600.
        os.replace(name,NAME,src_dir_fd=fd,dst_dir_fd=fd)
        try: os.fsync(fd)
        except OSError: return False  # Published; never claim it was unsaved.
        return True
    finally:
        try: os.unlink(name,dir_fd=fd)
        except FileNotFoundError: pass


class SecretStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _current(self):
        try:
            with _directory(self.directory) as fd:
                _private_directory(fd)
                return _read(fd)
        except FileNotFoundError:
            return 0,""  # Read/status never creates anything.
        except OSError:
            raise SecretStorageError() from None

    def status(self):
        number,value = self._current()
        return CredentialStatus(number,bool(value))

    def tvdb_credentials(self):
        _,value = self._current()
        if not value: raise ProviderConfigurationError()
        return Credentials(value)

    def initialize(self, tvdb_api_key=""):
        value = _value(tvdb_api_key)
        try:
            with _writer(self.directory) as fd:
                _private_directory(fd)
                try: _read(fd)
                except FileNotFoundError: pass
                else: raise ConfigurationConflict()
                durable = _publish(fd,1,value)
        except OSError:
            raise SecretStorageError() from None
        return SecretUpdateResult(CredentialStatus(1,bool(value)),True,durable,
                                  None if durable else "CONFIGURATION_DURABILITY_UNCONFIRMED")

    def update_tvdb_api_key(self, value, *, expected_revision):
        """Service-authorized replace/clear; optimistic revision, atomic write."""
        value = _value(value)
        revision(expected_revision)
        try:
            with _writer(self.directory) as fd:
                _private_directory(fd)
                number,old = _read(fd)
                if number!=expected_revision: raise ConfigurationConflict()
                if value==old: return SecretUpdateResult(CredentialStatus(number,bool(old)),False,True)
                number = revision(number+1)
                durable = _publish(fd,number,value)
        except OSError:
            raise SecretStorageError() from None
        return SecretUpdateResult(CredentialStatus(number,bool(value)),True,durable,
                                  None if durable else "CONFIGURATION_DURABILITY_UNCONFIRMED")
