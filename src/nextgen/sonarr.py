"""Fail-closed Sonarr API boundary for a future durable NextGen Keep worker.

This module does not authorize Keep, select trial files, journal command intent,
cleanup sources, or mark a library copy verified. Its network methods must only
be invoked after the caller pins and persists an exact approved Keep manifest.
In particular submit_copy() is NOT safe to replay after an uncertain response.
"""
from dataclasses import dataclass, field
import json
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import (HTTPRedirectHandler, ProxyHandler, Request,
                            build_opener)

from src.nextgen.acquisition.settings import endpoint, DownloadConfigurationError


class SonarrReview(ValueError):
    """A reviewable mismatch. Do not log upstream JSON, paths or credentials."""
    reason_code = "SONARR_IMPORT_REVIEW"
    def __init__(self):
        super().__init__("Review Sonarr series, episode identity, import candidate or configuration.")


class SonarrUnavailable(RuntimeError):
    reason_code = "SONARR_UNAVAILABLE"
    def __init__(self):
        super().__init__("Sonarr is unavailable; reconcile any submitted command before retrying.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True)
class SonarrOptions:
    base_url: str
    root_folder: str
    profile_name: str = "Anime"
    timeout_seconds: int = 15
    api_key: str = field(default="", repr=False)

    def __post_init__(self):
        try:
            url = endpoint(self.base_url)
        except DownloadConfigurationError:
            raise SonarrReview() from None
        from pathlib import PurePosixPath
        root = self.root_folder
        if (type(root) is not str or not root.startswith("/") or root.startswith("//")
                or root == "/" or len(root) > 4096 or str(PurePosixPath(root)) != root
                or any(x in (".", "..") for x in root.split("/"))):
            raise SonarrReview()
        if (type(self.profile_name) is not str or not 1 <= len(self.profile_name) <= 128
                or any(ord(c) < 32 or ord(c) == 127 for c in self.profile_name)):
            raise SonarrReview()
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise SonarrReview()
        if (type(self.api_key) is not str or not 1 <= len(self.api_key) <= 256
                or any(ord(c) <= 32 or ord(c) == 127 for c in self.api_key)):
            raise SonarrReview()
        object.__setattr__(self, "base_url", url)


class SonarrClient:
    """Bounded API v3 adapter. Exact TVDB/episode mapping always comes from caller."""
    def __init__(self, options: SonarrOptions, *, opener=None):
        if type(options) is not SonarrOptions:
            raise SonarrReview()
        self.options = options
        # Never honor environment proxies or 30x redirects for an internal API.
        self._open = opener or build_opener(ProxyHandler({}), _NoRedirect()).open

    def _request(self, method, route, payload=None, query=None):
        if method not in ("GET", "POST") or not route or any(x in route for x in "?&#\\"):
            raise SonarrReview()
        suffix = "?" + urlencode(query) if query else ""
        body = None if payload is None else json.dumps(payload, allow_nan=False,
                                     separators=(",", ":")).encode("utf-8")
        req = Request(self.options.base_url + "/api/v3/" + route + suffix,
                      data=body, method=method,
                      headers={"X-Api-Key": self.options.api_key,
                               "Accept": "application/json",
                               "Content-Type": "application/json"})
        try:
            with self._open(req, timeout=self.options.timeout_seconds) as response:
                if not 200 <= response.status < 300:
                    raise SonarrUnavailable()
                raw = response.read(1048577)
            if len(raw) > 1048576:
                raise SonarrUnavailable()
            return json.loads(raw) if raw else {}
        except (HTTPError, URLError, OSError, TimeoutError, UnicodeError,
                json.JSONDecodeError, ValueError):
            # Do not leak API key, URL, response body or remote rejection text.
            raise SonarrUnavailable() from None

    def _get(self, route, **query):
        return self._request("GET", route, query=query)

    @staticmethod
    def _positive(value):
        return type(value) is int and value > 0

    def ensure_series(self, tvdb_series_id):
        """Verify an existing entry or add exactly the TVDB-linked anime series.

        Never change root, profile or monitoring settings of an existing series.
        Missing-series admission is a mutating call: journal intent before this.
        """
        if not self._positive(tvdb_series_id):
            raise SonarrReview()
        profiles = self._get("qualityprofile")
        roots = self._get("rootfolder")
        if not isinstance(profiles, list) or not isinstance(roots, list):
            raise SonarrReview()
        named = [p for p in profiles if isinstance(p, dict)
                 and p.get("name") == self.options.profile_name
                 and self._positive(p.get("id"))]
        if len(named) != 1 or sum(isinstance(p, dict) and p.get("name") == self.options.profile_name
                                 for p in profiles) != 1:
            raise SonarrReview()
        if sum(isinstance(r, dict) and r.get("path") == self.options.root_folder
               for r in roots) != 1:
            raise SonarrReview()
        existing = self._get("series")
        if not isinstance(existing, list):
            raise SonarrReview()
        matches = [item for item in existing if isinstance(item, dict)
                   and item.get("tvdbId") == tvdb_series_id]
        if len(matches) > 1:
            raise SonarrReview()
        if matches:
            series = matches[0]
            if (not self._positive(series.get("id"))
                    or series.get("rootFolderPath") != self.options.root_folder
                    or series.get("qualityProfileId") != named[0]["id"]):
                raise SonarrReview()
            return series["id"], False
        lookup = self._get("series/lookup", term="tvdb:" + str(tvdb_series_id))
        if not isinstance(lookup, list):
            raise SonarrReview()
        found = [x for x in lookup if isinstance(x, dict) and x.get("tvdbId") == tvdb_series_id]
        if len(found) != 1:
            raise SonarrReview()
        series = dict(found[0]); series.pop("id", None)
        series.update({"tvdbId": tvdb_series_id, "qualityProfileId": named[0]["id"],
                       "rootFolderPath": self.options.root_folder, "seasonFolder": True,
                       "monitored": True, "monitorNewItems": "all", "seriesType": "anime",
                       "addOptions": {"monitor": "all", "searchForMissingEpisodes": False}})
        added = self._request("POST", "series", series)
        if not isinstance(added, dict) or not self._positive(added.get("id")):
            raise SonarrReview()
        if added.get("tvdbId") != tvdb_series_id:
            raise SonarrReview()
        return added["id"], True

    def manual_import_preview(self, sonarr_id, items):
        """Resolve canonical Sonarr IDs and reprocess exact stage candidates.

        items: ({path, season, episode, tvdb_episode_id}, ...). A successful
        preview has NO library side effect and is not authorization to submit.
        """
        if not self._positive(sonarr_id) or not isinstance(items, (list, tuple)) or not items:
            raise SonarrReview()
        episodes = self._get("episode", seriesId=sonarr_id)
        if not isinstance(episodes, list):
            raise SonarrReview()
        selected = []
        visited = set()
        for item in items:
            if (type(item) is not dict or set(item) !=
                    {"path", "season", "episode", "tvdb_episode_id"}):
                raise SonarrReview()
            path, season, number, tvdb_episode = (item[x] for x in
                        ("path", "season", "episode", "tvdb_episode_id"))
            if (type(path) is not str or not path.startswith("/") or path.startswith("//")
                    or ".." in path.split("/") or not path.endswith((".mkv", ".mp4"))
                    or len(path) > 4096 or type(season) is not int or season < 0
                    or not self._positive(number) or not self._positive(tvdb_episode)
                    or path in visited):
                raise SonarrReview()
            visited.add(path)
            matched = [e for e in episodes if isinstance(e, dict)
                       and e.get("seasonNumber") == season and e.get("episodeNumber") == number]
            if len(matched) != 1 or not self._positive(matched[0].get("id")):
                raise SonarrReview()
            canonical = matched[0]
            # Sonarr versions may omit this field. When present it must agree.
            if canonical.get("tvdbId") is not None and canonical["tvdbId"] != tvdb_episode:
                raise SonarrReview()
            # No seriesId on folder lookup: that instead scans the series library.
            folder = path.rsplit("/", 1)[0]
            candidates = self._get("manualimport", folder=folder)
            if not isinstance(candidates, list):
                raise SonarrReview()
            candidates = [c for c in candidates if isinstance(c, dict) and c.get("path") == path]
            if len(candidates) != 1:
                raise SonarrReview()
            candidate = candidates[0]
            if not isinstance(candidate.get("quality"), dict) or not candidate.get("languages"):
                raise SonarrReview()
            payload = [{"path": path, "seriesId": sonarr_id, "seasonNumber": season,
                        "episodeIds": [canonical["id"]],
                        "quality": candidate["quality"], "languages": candidate["languages"],
                        "releaseGroup": candidate.get("releaseGroup") or "",
                        "indexerFlags": candidate.get("indexerFlags") or 0,
                        "releaseType": candidate.get("releaseType") or 0}]
            processed = self._request("POST", "manualimport", payload)
            if not isinstance(processed, list) or len(processed) != 1 or not isinstance(processed[0], dict):
                raise SonarrReview()
            confirmed = processed[0]
            ids = confirmed.get("episodes")
            if (confirmed.get("path") != path or confirmed.get("seriesId") != sonarr_id
                    or not isinstance(ids, list) or len(ids) != 1
                    or not isinstance(ids[0], dict) or ids[0].get("id") != canonical["id"]
                    or confirmed.get("rejections") or not isinstance(confirmed.get("quality"), dict)
                    or not confirmed.get("languages")):
                raise SonarrReview()
            selected.append({"path": path, "seriesId": sonarr_id,
                             "episodeIds": [canonical["id"]],
                             "quality": confirmed["quality"], "languages": confirmed["languages"]})
        return selected

    def submit_copy(self, selected):
        """Send the irreversible command ONCE after caller has journaled intent.

        A timeout/connection loss is *uncertain*, not permission to replay.
        Reconcile Sonarr command history and file inventory before resubmitting.
        """
        if not isinstance(selected, list) or not selected:
            raise SonarrReview()
        if any(not isinstance(item, dict) or
               set(item) != {"path", "seriesId", "episodeIds", "quality", "languages"}
               for item in selected):
            raise SonarrReview()
        response = self._request("POST", "command",
                                 {"name": "ManualImport", "files": selected, "importMode": "copy"})
        if not isinstance(response, dict) or not self._positive(response.get("id")):
            raise SonarrReview()
        return response["id"]

    def command_status(self, command_id):
        """Inspect one recorded command. Never search by guessed source filename."""
        if not self._positive(command_id):
            raise SonarrReview()
        response=self._get("command/"+str(command_id))
        if not isinstance(response,dict) or response.get("id")!=command_id:
            raise SonarrReview()
        value=response.get("status")
        if value not in ("queued","started","completed","failed","aborted","cancelled"):
            raise SonarrReview()
        return value

    def inventory(self, sonarr_id):
        """Read episode and file references; never infer proof from filenames."""
        if not self._positive(sonarr_id):
            raise SonarrReview()
        episodes = self._get("episode", seriesId=sonarr_id)
        files = self._get("episodefile", seriesId=sonarr_id)
        if not isinstance(episodes, list) or not isinstance(files, list):
            raise SonarrReview()
        return episodes, files
