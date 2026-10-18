"""Read-only qBittorrent 4.5.2 and Sonarr v3 HTTP adapters.

No network on import. No mutation endpoints. No implicit TLS bypass.
Python 3.11 compatible; standard library only.
"""
import http.cookiejar
import json
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass


class AdapterError(RuntimeError):
    pass


def _origin(url, *, scheme):
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != scheme or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError('invalid endpoint or protocol')
    if parsed.path not in ('', '/') or parsed.query or parsed.fragment:
        raise ValueError('endpoint must be a bare origin')
    return url.rstrip('/')


@dataclass(frozen=True)
class Torrent:
    torrent_hash: str
    name: str
    state: str
    save_path: str
    progress: float


class QBittorrentReadOnly:
    """Cookie-authenticated read-only Web API; no torrent mutations exposed."""
    def __init__(self, base_url, username, password, *, timeout=8):
        self.base_url = _origin(base_url, scheme='http')
        if not username or not password:
            raise ValueError('qB credentials required')
        self._username = username
        self._password = password
        self.timeout = timeout
        self._jar = http.cookiejar.CookieJar()
        self._opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self._jar),
                                                   urllib.request.ProxyHandler({}))
        self._authenticated = False

    def _request(self, path, *, form=None):
        if not path.startswith('/api/v2/'):
            raise AdapterError('invalid qB API path')
        url = self.base_url + path
        headers = {'Referer': self.base_url + '/', 'Origin': self.base_url}
        if form is not None:
            headers['Content-Type'] = 'application/x-www-form-urlencoded'
        payload = urllib.parse.urlencode(form).encode() if form is not None else None
        req = urllib.request.Request(url, data=payload, headers=headers)
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                return resp.read().decode('utf-8')
        except urllib.error.HTTPError as exc:
            raise AdapterError('qB API HTTP {}'.format(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise AdapterError('qB API connection failed') from exc

    def login(self):
        reply = self._request('/api/v2/auth/login', form={'username': self._username, 'password': self._password})
        if reply.strip() != 'Ok.' or not any(c.name == 'SID' for c in self._jar):
            raise AdapterError('qB authentication failed')
        self._authenticated = True

    def _get(self, path):
        if not self._authenticated:
            raise AdapterError('qB login required')
        return self._request(path)

    def version(self):
        return self._get('/api/v2/app/version').strip()

    def torrents(self):
        try:
            records = json.loads(self._get('/api/v2/torrents/info'))
        except (ValueError, TypeError) as exc:
            raise AdapterError('invalid qB inventory response') from exc
        if not isinstance(records, list):
            raise AdapterError('qB inventory must be a list')
        results = []
        seen = set()
        for item in records:
            if not isinstance(item, dict):
                raise AdapterError('invalid torrent record')
            h = item.get('hash')
            if not isinstance(h, str) or len(h) != 40 or any(ch not in '0123456789abcdefABCDEF' for ch in h):
                raise AdapterError('invalid torrent hash')
            if h.lower() in seen:
                raise AdapterError('duplicate torrent hash')
            seen.add(h.lower())
            try:
                results.append(Torrent(h.lower(), str(item['name']), str(item['state']),
                                       str(item['save_path']), float(item['progress'])))
            except (KeyError, TypeError, ValueError) as exc:
                raise AdapterError('incomplete torrent record') from exc
        return results


class SonarrReadOnly:
    """Read-only Sonarr API with mandatory hostname-verified HTTPS."""
    def __init__(self, base_url, api_key, *, ca_bundle=None, timeout=8):
        self.base_url = _origin(base_url, scheme='https')
        if not api_key:
            raise ValueError('Sonarr API key required')
        self._key = api_key
        self.timeout = timeout
        self._context = ssl.create_default_context(cafile=ca_bundle)
        self._opener = urllib.request.build_opener(urllib.request.HTTPSHandler(context=self._context),
                                                   urllib.request.ProxyHandler({}))

    def _get(self, path):
        if not path.startswith('/api/v3/'):
            raise AdapterError('invalid Sonarr API path')
        req = urllib.request.Request(self.base_url + path, headers={'X-Api-Key': self._key})
        try:
            with self._opener.open(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode('utf-8'))
        except urllib.error.HTTPError as exc:
            raise AdapterError('Sonarr API HTTP {}'.format(exc.code)) from exc
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
            raise AdapterError('Sonarr API request failed') from exc
        return payload

    def status(self):
        data = self._get('/api/v3/system/status')
        if not isinstance(data, dict) or 'version' not in data:
            raise AdapterError('invalid Sonarr status')
        return {'version': data['version'], 'appName': data.get('appName')}

    def series(self):
        data = self._get('/api/v3/series')
        if not isinstance(data, list):
            raise AdapterError('invalid Sonarr series listing')
        return data

    def episodes(self, series_id):
        if type(series_id) is not int or series_id <= 0:
            raise ValueError('positive Sonarr series ID required')
        data = self._get('/api/v3/episode?seriesId={}'.format(series_id))
        if not isinstance(data, list):
            raise AdapterError('invalid Sonarr episodes listing')
        return data
