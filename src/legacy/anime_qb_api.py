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

    def torrent_identity(self, infohash):
        """Exact-hash read of category/tags without requiring a ready save path."""
        infohash=_hash(infohash)
        records=json.loads(self._request("torrents/info?"+urlencode({"hashes":infohash})))
        if not isinstance(records,list):
            raise ValueError("Invalid qBittorrent torrent list")
        matched=[item for item in records if isinstance(item,dict)
                 and str(item.get("hash","")).lower()==infohash]
        if len(matched)>1:
            raise ValueError("Duplicate qBittorrent torrent record")
        return matched[0] if matched else None

    def ensure_category(self,category):
        """Create only our missing fixed category, without changing other categories."""
        if category!="anime-discovery":
            raise ValueError("Unsupported Anime Discovery category")
        existing=json.loads(self._request("torrents/categories"))
        if not isinstance(existing,dict):
            raise ValueError("Invalid qBittorrent category inventory")
        if category in existing:
            return
        # A concurrent administrator/category creator might win the race.
        # Let a non-200 response fail rather than silently submit untagged.
        response=self._request("torrents/createCategory",
                               {"category":category,"savePath":""})
        if response.strip() not in (b"",b"Ok."):
            raise RuntimeError("qBittorrent category creation unconfirmed")
        verify=json.loads(self._request("torrents/categories"))
        if not isinstance(verify,dict) or category not in verify:
            raise RuntimeError("qBittorrent category creation not visible")

    def contains_hash(self, infohash):
        infohash=_hash(infohash)
        records=json.loads(self._request("torrents/info?"+urlencode({"hashes":infohash})))
        if not isinstance(records,list):
            raise ValueError("Invalid torrent list")
        return any(isinstance(item,dict) and str(item.get("hash","")).lower()==infohash
                   for item in records)

    def torrent_inventory(self):
        """Read all torrents to detect shared physical download targets."""
        records=json.loads(self._request("torrents/info"))
        if not isinstance(records,list):
            raise ValueError("Invalid qBittorrent torrent inventory")
        return records

    def torrent_files(self, infohash):
        """Read exact per-torrent file inventory; no torrent state change."""
        records=json.loads(self._request("torrents/files?"+urlencode({"hash":_hash(infohash)})))
        if not isinstance(records,list) or any(not isinstance(item,dict) or
                 not isinstance(item.get("name"),str) for item in records):
            raise ValueError("Invalid qBittorrent torrent file inventory")
        return records



    def web_api_version(self):
        """Read the server's API capability, not its Debian package version."""
        import re
        raw = self._request("app/webapiVersion")
        try:
            value = raw.decode("ascii").strip()
        except (AttributeError, UnicodeDecodeError) as exc:
            raise RuntimeError("Invalid qBittorrent Web API version") from exc
        match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", value)
        if not match:
            raise RuntimeError("Unrecognized qBittorrent Web API version")
        parts = tuple(int(match.group(i) or 0) for i in (1, 2, 3))
        # Version 2.8.2 provides stable per-file indexes; old APIs cannot
        # safely execute our explicit indexed file-selection workflow.
        if not ((2, 8, 2) <= parts < (3, 0, 0)):
            raise RuntimeError("Unsupported qBittorrent Web API")
        return parts

    def _lifecycle_endpoints(self):
        """Web API <2.11: pause/resume; API >=2.11: stop/start."""
        return (("torrents/stop", "torrents/start")
                if self.web_api_version() >= (2, 11, 0)
                else ("torrents/pause", "torrents/resume"))

    def _owned_torrent(self, infohash):
        import re
        record = self.torrent_identity(infohash)
        if not record or record.get("category") != "anime-discovery":
            raise PermissionError("Not an Anime Discovery torrent")
        if not any(re.fullmatch(r"ad-[0-9a-f]{32}",tag.strip())
                   for tag in str(record.get("tags") or "").split(",")):
            raise PermissionError("Anime Discovery ownership marker missing")
        # Database-side token and provenance comparison are also mandatory
        # for the future acquisition worker; this adapter cannot prove them.
        return record

    def stop_owned_torrent(self, infohash):
        """Stop exactly one marker-tagged torrent. Never act on all torrents.

        The worker must also verify the durable database ownership record.
        """
        if not self.allow_writes:
            raise PermissionError("qBittorrent writes disabled")
        infohash = _hash(infohash)
        self._owned_torrent(infohash)
        endpoint, _ = self._lifecycle_endpoints()
        response = self._request(endpoint, {"hashes": infohash})
        if response.strip() not in (b"", b"Ok."):
            raise RuntimeError("qBittorrent stop not acknowledged")
        after = self._owned_torrent(infohash)
        if after.get("state") not in (
                "pausedDL", "pausedUP", "stoppedDL", "stoppedUP"):
            raise RuntimeError("qBittorrent stop not yet confirmed")
        return after["state"]

    def resume_owned_metadata(self, infohash):
        """Retry an owned stopped magnet ONLY while it has no file metadata.

        This is an intentionally bounded pre-selection discovery window.
        A caller MUST confirm the DB ownership marker before calling.
        Once a file list exists, use start_selected_torrent instead.
        """
        if not self.allow_writes:
            raise PermissionError("qBittorrent writes disabled")
        infohash = _hash(infohash)
        record = self._owned_torrent(infohash)
        if record.get("state") not in (
                "stoppedDL", "stoppedUP", "pausedDL", "pausedUP"):
            raise RuntimeError("Metadata retry requires stopped torrent")
        if self.torrent_files(infohash):
            raise RuntimeError("Refusing unselected resume: file metadata is available")
        _, endpoint = self._lifecycle_endpoints()
        response = self._request(endpoint, {"hashes": infohash})
        if response.strip() not in (b"", b"Ok."):
            raise RuntimeError("Metadata retry not acknowledged")
        return True

    def start_selected_torrent(self, infohash, *, wanted_indices, skip_indices):
        """Start only after stopped-state and full priority readback.

        No live worker invokes this method yet. E01-first eligibility and
        durable JP+EN proof for later episodes must be checked by the worker.
        """
        if not self.allow_writes:
            raise PermissionError("qBittorrent writes disabled")
        infohash = _hash(infohash)
        if (not isinstance(wanted_indices, (list, tuple))
                or not wanted_indices
                or not isinstance(skip_indices, (list, tuple))
                or any(type(i) is not int or i < 0
                       for i in [*wanted_indices, *skip_indices])):
            raise ValueError("Invalid wanted or skipped indices")
        wanted, skipped = set(wanted_indices), set(skip_indices)
        if (len(wanted) != len(wanted_indices)
                or len(skipped) != len(skip_indices) or wanted & skipped):
            raise ValueError("Duplicate or overlapping file indices")
        torrent = self._owned_torrent(infohash)
        if torrent.get("state") not in (
                "pausedDL", "pausedUP", "stoppedDL", "stoppedUP"):
            raise RuntimeError("Torrent is not stopped")
        files = self.torrent_files(infohash)
        priorities = {}
        for file in files:
            idx, priority = file.get("index"), file.get("priority")
            if (type(idx) is not int or idx < 0
                    or idx in priorities or type(priority) is not int):
                raise RuntimeError("Incomplete torrent file manifest")
            priorities[idx] = priority
        if not priorities or set(priorities) != wanted | skipped:
            raise RuntimeError("Torrent file list differs from approved selection")
        if any(priorities[i] != (1 if i in wanted else 0) for i in priorities):
            raise RuntimeError("Torrent file priorities differ from approved selection")
        _, endpoint = self._lifecycle_endpoints()
        response = self._request(endpoint, {"hashes": infohash})
        if response.strip() not in (b"", b"Ok."):
            raise RuntimeError("qBittorrent start not acknowledged")
        # Async state changes; acknowledgment means command accepted, not
        # completed transfer. Worker monitors exact file progress afterward.
        return True

    def apply_stopped_file_selection(self, infohash, *, wanted_indices, skip_indices):
        """Set and read back all file priorities on an owned, STOPPED torrent.

        This does not resume a torrent, and is not called by the live worker.
        The caller must separately verify the app's durable ownership marker
        and transactionally reserve the episode mapping. Any missing or
        inconsistent metadata fails closed; never resume on an exception.
        """
        import re
        infohash = _hash(infohash)
        if not self.allow_writes:
            raise PermissionError("qBittorrent writes disabled")
        for indices in (wanted_indices, skip_indices):
            if (not isinstance(indices, (list, tuple)) or
                    any(type(x) is not int or x < 0 for x in indices) or
                    len(set(indices)) != len(indices)):
                raise ValueError("Invalid torrent file indices")
        wanted = set(wanted_indices)
        skipped = set(skip_indices)
        if wanted & skipped:
            raise ValueError("Overlapping wanted and skipped files")
        detail = self.torrent_identity(infohash)
        if not detail or detail.get("category") != "anime-discovery":
            raise PermissionError("Not an Anime Discovery torrent")
        tags = str(detail.get("tags") or "").split(",")
        if not any(re.fullmatch(r"ad-[0-9a-f]{32}",tag.strip()) for tag in tags):
            raise PermissionError("Owned torrent marker missing")
        if detail.get("state") not in ("stoppedDL", "pausedDL", "stoppedUP", "pausedUP"):
            raise RuntimeError("Torrent must remain stopped before selection")
        before = self.torrent_files(infohash)
        indices_by_file = {}
        for entry in before:
            index = entry.get("index")
            if (type(index) is not int or index < 0 or
                    index in indices_by_file or
                    type(entry.get("priority")) is not int):
                raise ValueError("Incomplete qBittorrent file priorities")
            indices_by_file[index] = entry["priority"]
        if not indices_by_file or set(indices_by_file) != wanted | skipped:
            raise ValueError("Selection must cover every torrent file exactly")
        # Skip unwanted files BEFORE assigning wanted priorities.
        for selection, priority in ((skipped, 0), (wanted, 1)):
            if selection:
                answer = self._request("torrents/filePrio", {
                    "hash": infohash,
                    "id": "|".join(str(x) for x in sorted(selection)),
                    "priority": str(priority),
                })
                if answer.strip() not in (b"", b"Ok."):
                    raise RuntimeError("File priority update not acknowledged")
        after = self.torrent_files(infohash)
        actual = {}
        for entry in after:
            index = entry.get("index")
            if (type(index) is not int or index in actual or index < 0 or
                    type(entry.get("priority")) is not int):
                raise RuntimeError("Incomplete file priority readback")
            actual[index] = entry["priority"]
        if (set(actual) != set(indices_by_file) or
                any(actual[index] != (1 if index in wanted else 0)
                    for index in actual)):
            raise RuntimeError("File priority verification failed; torrent must remain stopped")
        detail_after = self.torrent_identity(infohash)
        if (not detail_after or detail_after.get("state")
                not in ("stoppedDL", "pausedDL", "stoppedUP", "pausedUP")):
            raise RuntimeError("Torrent became active during priority selection")
        return {"wanted_indices": sorted(wanted), "skip_indices": sorted(skipped)}

    def add_magnet(self, magnet_uri, *, category=None, tag=None, stopped=False, save_path=None):
        if not isinstance(magnet_uri,str) or not magnet_uri.startswith("magnet:?"):
            raise ValueError("Invalid magnet")
        if category is not None and category!="anime-discovery":
            raise ValueError("Unsupported Anime Discovery category")
        if tag is not None:
            import re
            if category!="anime-discovery" or not re.fullmatch(r"ad-[0-9a-f]{32}",tag):
                raise ValueError("Invalid Anime Discovery ownership marker")
        if type(stopped) is not bool:
            raise ValueError("stopped must be boolean")
        # On qBittorrent 4.5.2 this maps to paused=true; Web API >=2.11
        # renamed the request field to stopped=true.
        stop_key = ("stopped" if self.web_api_version() >= (2, 11, 0)
                    else "paused") if stopped else None
        fields={"urls":magnet_uri}
        if save_path is not None:
            from pathlib import Path
            if (not isinstance(save_path,str) or not Path(save_path).is_absolute()
                    or ".." in Path(save_path).parts):
                raise ValueError("Invalid absolute qBittorrent save path")
            fields["savepath"]=save_path
        if stop_key:
            fields[stop_key] = "true"
        if category is not None:
            self.ensure_category(category)
            fields["category"]=category
        if tag is not None:
            fields["tags"]=tag
        response=self._request("torrents/add",fields)
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
