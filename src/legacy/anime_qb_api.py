"""Minimal qBittorrent Web API adapter with explicit write opt-in.

Injected opener makes the HTTP protocol testable offline. No automatic
connection, torrent submission or deletion is performed at import time.
"""
import json
from urllib.parse import urlencode
from urllib.request import Request, build_opener, HTTPCookieProcessor
from http.cookiejar import CookieJar

class QBittorrentAPI:
    def __init__(self, base_url, *, opener=None, allow_writes=False, timeout=10):
        from urllib.parse import urlsplit
        parts=urlsplit(base_url)
        if parts.scheme not in ("http","https") or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
            raise ValueError("Invalid qBittorrent URL")
        self.base_url=base_url.rstrip("/")
        self.opener=opener or build_opener(HTTPCookieProcessor(CookieJar()))
        self.allow_writes=allow_writes
        self.timeout=timeout

    def _request(self, endpoint, data=None):
        if data is not None and not self.allow_writes:
            raise PermissionError("qBittorrent writes disabled")
        request=Request(self.base_url+"/api/v2/"+endpoint,
                        data=urlencode(data).encode() if data is not None else None)
        with self.opener.open(request,timeout=self.timeout) as response:
            if response.status!=200:
                raise RuntimeError("qBittorrent HTTP failure")
            return response.read()

    def login(self, username, password):
        if not isinstance(username,str) or not username or not isinstance(password,str) or not password:
            raise ValueError("Missing qBittorrent credentials")
        # Authentication is a session mutation, separate from torrent writes.
        request=Request(self.base_url+"/api/v2/auth/login",
                        data=urlencode({"username":username,"password":password}).encode())
        with self.opener.open(request,timeout=self.timeout) as response:
            if response.status!=200 or response.read().strip()!=b"Ok.":
                raise PermissionError("qBittorrent authentication failed")

    def torrent_details(self, infohash):
        """Read the exact torrent's save path before authorizing any cleanup."""
        infohash=_hash(infohash)
        records=json.loads(self._request("torrents/info?"+urlencode({"hashes":infohash})))
        if not isinstance(records,list):
            raise ValueError("Invalid torrent inventory")
        matched=[item for item in records
                 if isinstance(item,dict) and str(item.get("hash","")).lower()==infohash]
        if len(matched)>1:
            raise ValueError("Duplicate qBittorrent torrent record")
        if matched and (not isinstance(matched[0].get("save_path"),str)
                        or not matched[0]["save_path"].startswith("/")):
            raise ValueError("Torrent save path unavailable")
        return matched[0] if matched else None

    def contains_hash(self, infohash):
        infohash=_hash(infohash)
        records=json.loads(self._request("torrents/info?"+urlencode({"hashes":infohash})))
        if not isinstance(records,list):
            raise ValueError("Invalid torrent list")
        return any(isinstance(item,dict) and str(item.get("hash","")).lower()==infohash
                   for item in records)

    def torrent_files(self, infohash):
        """Read exact per-torrent file inventory; no torrent state change."""
        records=json.loads(self._request("torrents/files?"+urlencode({"hash":_hash(infohash)})))
        if not isinstance(records,list) or any(not isinstance(item,dict) or
                 not isinstance(item.get("name"),str) for item in records):
            raise ValueError("Invalid qBittorrent torrent file inventory")
        return records

    def add_magnet(self, magnet_uri):
        if not isinstance(magnet_uri,str) or not magnet_uri.startswith("magnet:?"):
            raise ValueError("Invalid magnet")
        response=self._request("torrents/add",{"urls":magnet_uri})
        if response.strip()!=b"Ok.":
            raise RuntimeError("Torrent add not acknowledged")

    def remove_torrent(self, infohash, *, delete_files=False):
        if type(delete_files) is not bool:
            raise ValueError("delete_files must be boolean")
        response=self._request("torrents/delete",
                               {"hashes":_hash(infohash),"deleteFiles":"true" if delete_files else "false"})
        if response.strip() not in (b"",b"Ok."):
            raise RuntimeError("Torrent removal not acknowledged")

def _hash(value):
    if not isinstance(value,str) or len(value) not in (40,64) or any(c not in "0123456789abcdef" for c in value.lower()):
        raise ValueError("Invalid infohash")
    return value.lower()
