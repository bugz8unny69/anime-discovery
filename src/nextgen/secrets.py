"""Service-owned private credential repository; no HTTP, environment fallback or SQL.

Public results contain presence/revision only. Trusted provider code obtains a
credential object explicitly; values never appear in repr, history or logs.
"""
from dataclasses import dataclass
import json
import os
import re
from pathlib import Path
import stat
import uuid

from src.nextgen.acquisition.settings import DownloadCredentials
from src.nextgen.configuration import _directory, _writer, _write_bytes
from src.nextgen.configuration_schema import ConfigurationError, ConfigurationConflict, decode, revision
from src.nextgen.providers.errors import ProviderConfigurationError
from src.nextgen.providers.http import Credentials

NAME = "secrets.json"


class SecretStorageError(ConfigurationError):
    reason_code = "SECRET_STORAGE_UNAVAILABLE"
    def __init__(self):
        ValueError.__init__(self,"Credentials could not be accessed safely.")


@dataclass(frozen=True)
class CredentialStatus:
    revision: int
    tvdb_api_key_configured: bool
    qbittorrent_configured: bool = False
    webhook_configured: bool = False
    management_configured: bool = False
    sonarr_configured: bool = False
    jellyfin_configured: bool = False


@dataclass(frozen=True)
class SecretUpdateResult:
    status: CredentialStatus
    saved: bool
    durability_confirmed: bool
    reason_code: str | None = None


@dataclass(frozen=True,repr=False)
class AccessCredentials:
    webhook_token: str
    management_token: str


def _access_value(value):
    if type(value) is not str or value and not re.fullmatch(r'[A-Za-z0-9_-]{32,256}',value):raise SecretStorageError()
    return value


def _access_values(webhook,management):
    result={'webhook_token':_access_value(webhook),'management_token':_access_value(management)}
    if webhook and management and webhook==management:raise SecretStorageError()
    return result


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
                or type(document["schema_version"]) is not int or document["schema_version"] not in (1,2,3,4,5)
                or type(document["credentials"]) is not dict):raise SecretStorageError()
        version=document['schema_version']
        expected={'tvdb_api_key'} if version==1 else {'tvdb_api_key','qbittorrent_username','qbittorrent_password'}
        if version>=3:expected|={'webhook_token','management_token'}
        if version>=4:expected.add('sonarr_api_key')
        if version>=5:expected.add('jellyfin_api_key')
        if set(document['credentials'])!=expected:raise SecretStorageError()
        values={'tvdb_api_key':_value(document['credentials']['tvdb_api_key']),
                'qbittorrent_username':'','qbittorrent_password':'','webhook_token':'','management_token':'',
                'sonarr_api_key':'','jellyfin_api_key':''}
        if version>=2:
            values.update(_download_values(document['credentials']['qbittorrent_username'],document['credentials']['qbittorrent_password']))
        if version>=3:values.update(_access_values(document['credentials']['webhook_token'],document['credentials']['management_token']))
        if version>=4:values['sonarr_api_key']=_value(document['credentials']['sonarr_api_key'])
        if version>=5:values['jellyfin_api_key']=_value(document['credentials']['jellyfin_api_key'])
        return revision(document['revision']),values,version
    except (ValueError,TypeError,KeyError):
        raise SecretStorageError() from None


def _private_directory(fd):
    metadata = os.fstat(fd)
    if metadata.st_uid!=os.geteuid() or metadata.st_mode & 0o022:
        raise SecretStorageError()


def _publish(fd, current_revision, values, *, version=2):
    name = ".secrets-"+uuid.uuid4().hex+".tmp"
    keys={'tvdb_api_key'}
    if version>=2:keys|={'qbittorrent_username','qbittorrent_password'}
    if version>=3:keys|={'webhook_token','management_token'}
    if version>=4:keys.add('sonarr_api_key')
    if version>=5:keys.add('jellyfin_api_key')
    raw = (json.dumps({"schema_version":version,"revision":current_revision,
                       "credentials":{key:values[key] for key in keys}},sort_keys=True)+"\n").encode()
    try:
        _write_bytes(fd,name,raw)  # Always new service-owned mode 0600.
        os.replace(name,NAME,src_dir_fd=fd,dst_dir_fd=fd)
        try: os.fsync(fd)
        except OSError: return False  # Published; never claim it was unsaved.
        return True
    finally:
        try: os.unlink(name,dir_fd=fd)
        except FileNotFoundError: pass


def _download_values(username,password):
    if type(username) is not str or type(password) is not str:raise SecretStorageError()
    if username or password:
        try:DownloadCredentials(username,password)
        except ValueError:raise SecretStorageError() from None
    return {'qbittorrent_username':username,'qbittorrent_password':password}


def _status(number,values):
    return CredentialStatus(number,bool(values['tvdb_api_key']),bool(values['qbittorrent_username'] and values['qbittorrent_password']),
                            bool(values.get('webhook_token')),bool(values.get('management_token')),bool(values.get('sonarr_api_key')),bool(values.get('jellyfin_api_key')))


class SecretStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _current(self):
        try:
            with _directory(self.directory) as fd:
                _private_directory(fd)
                return _read(fd)
        except FileNotFoundError:
            return 0,{'tvdb_api_key':'','qbittorrent_username':'','qbittorrent_password':'','webhook_token':'','management_token':'','sonarr_api_key':'','jellyfin_api_key':''},2
        except OSError:
            raise SecretStorageError() from None

    def status(self):
        number,values,_ = self._current()
        return _status(number,values)

    def tvdb_credentials(self):
        _,values,_ = self._current()
        if not values['tvdb_api_key']:raise ProviderConfigurationError()
        return Credentials(values['tvdb_api_key'])

    def qbittorrent_credentials(self):
        _,values,_ = self._current()
        return DownloadCredentials(values['qbittorrent_username'],values['qbittorrent_password'])

    def access_credentials(self):
        _,values,_=self._current()
        return AccessCredentials(values['webhook_token'],values['management_token'])

    def sonarr_api_key(self):
        _,values,_=self._current()
        if not values['sonarr_api_key']:raise SecretStorageError()
        return values['sonarr_api_key']

    def jellyfin_api_key(self):
        _,values,_=self._current()
        if not values['jellyfin_api_key']:raise SecretStorageError()
        return values['jellyfin_api_key']

    def initialize(self, tvdb_api_key='', *, qbittorrent_username='', qbittorrent_password='', webhook_token='', management_token='', sonarr_api_key='', jellyfin_api_key=''):
        values={'tvdb_api_key':_value(tvdb_api_key),**_download_values(qbittorrent_username,qbittorrent_password),
                **_access_values(webhook_token,management_token),'sonarr_api_key':_value(sonarr_api_key),'jellyfin_api_key':_value(jellyfin_api_key)}
        try:
            with _writer(self.directory) as fd:
                _private_directory(fd)
                try:_read(fd)
                except FileNotFoundError:pass
                else:raise ConfigurationConflict()
                durable=_publish(fd,1,values,version=5 if jellyfin_api_key else 4 if sonarr_api_key else 3 if webhook_token or management_token else 2)
        except OSError:raise SecretStorageError() from None
        return SecretUpdateResult(_status(1,values),True,durable,
                                  None if durable else 'CONFIGURATION_DURABILITY_UNCONFIRMED')

    def _update(self, changes, *, expected_revision, upgrade=False, minimum_version=1):
        revision(expected_revision)
        try:
            with _writer(self.directory) as fd:
                _private_directory(fd)
                number,old,version=_read(fd)
                if number!=expected_revision:raise ConfigurationConflict()
                values={**old,**changes}
                _access_values(values['webhook_token'],values['management_token'])
                if values==old:return SecretUpdateResult(_status(number,old),False,True)
                number=revision(number+1)
                durable=_publish(fd,number,values,version=max(version,2 if upgrade else minimum_version))
        except OSError:raise SecretStorageError() from None
        return SecretUpdateResult(_status(number,values),True,durable,
                                  None if durable else 'CONFIGURATION_DURABILITY_UNCONFIRMED')

    def update_tvdb_api_key(self, value, *, expected_revision):
        return self._update({'tvdb_api_key':_value(value)},expected_revision=expected_revision)

    def update_qbittorrent_credentials(self, username, password, *, expected_revision):
        """Explicitly replace/clear the pair; v1 upgrades only when this changes it."""
        return self._update(_download_values(username,password),expected_revision=expected_revision,upgrade=True)

    def update_access_tokens(self, webhook_token, management_token, *, expected_revision):
        return self._update(_access_values(webhook_token,management_token),expected_revision=expected_revision,minimum_version=3)

    def update_sonarr_api_key(self, value, *, expected_revision):
        return self._update({'sonarr_api_key':_value(value)},expected_revision=expected_revision,minimum_version=4)

    def update_jellyfin_api_key(self, value, *, expected_revision):
        return self._update({'jellyfin_api_key':_value(value)},expected_revision=expected_revision,minimum_version=5)
