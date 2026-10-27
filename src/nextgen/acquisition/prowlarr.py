"""Read-only Prowlarr search and conservative candidate selection.

Adapted from the legacy anime_prowlarr_search.py and anime_release_matching.py.
Search results are untrusted hints, NEVER episode identity, torrent ownership,
or permission to reserve, submit, download, stage or keep media.
"""
from dataclasses import dataclass, field
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, build_opener

from src.nextgen.acquisition.settings import DownloadConfigurationError, endpoint
from src.nextgen.providers.http import NoRedirect

MAX_RESPONSE = 2 * 1024 * 1024
MAX_RESULTS = 500
BTIH = re.compile(r"[0-9a-f]{40}")


class ProwlarrConfigurationError(ValueError):
    reason_code = "PROWLARR_CONFIGURATION_INVALID"

    def __init__(self):
        super().__init__("Prowlarr connection settings are incomplete or invalid.")


class ProwlarrUnavailable(RuntimeError):
    reason_code = "PROWLARR_UNAVAILABLE"

    def __init__(self):
        super().__init__("Prowlarr search is temporarily unavailable.")


class ProwlarrInvalidResponse(RuntimeError):
    reason_code = "PROWLARR_RESPONSE_INVALID"

    def __init__(self):
        super().__init__("Prowlarr returned an unusable search response.")


class ProwlarrAuthenticationError(RuntimeError):
    reason_code = "PROWLARR_AUTH_FAILED"

    def __init__(self):
        super().__init__("Prowlarr rejected its configured API key.")


@dataclass(frozen=True)
class ProwlarrOptions:
    base_url: str
    timeout_seconds: int = 30

    def __post_init__(self):
        try:
            url = endpoint(self.base_url)
        except DownloadConfigurationError:
            raise ProwlarrConfigurationError() from None
        if type(self.timeout_seconds) is not int or not 1 <= self.timeout_seconds <= 60:
            raise ProwlarrConfigurationError()
        object.__setattr__(self, "base_url", url)


@dataclass(frozen=True, repr=False)
class ProwlarrCredentials:
    api_key: str = field(repr=False)

    def __post_init__(self):
        if (type(self.api_key) is not str or not 1 <= len(self.api_key) <= 1024
                or any(ord(c) < 33 or ord(c) == 127 for c in self.api_key)):
            raise ProwlarrConfigurationError()


class ProwlarrClient:
    """Explicit, bounded GET. No redirects and no download endpoint calls."""

    def __init__(self, options, credentials, *, opener=None):
        if type(options) is not ProwlarrOptions or type(credentials) is not ProwlarrCredentials:
            raise ProwlarrConfigurationError()
        self.options = options
        self._credentials = credentials
        self._open = opener or build_opener(NoRedirect()).open

    def search(self, title):
        if (type(title) is not str or not title.strip() or len(title) > 200
                or any(ord(c) < 32 or ord(c) == 127 for c in title)):
            raise ValueError("Invalid Prowlarr title query")
        url = self.options.base_url + "/api/v1/search?" + urlencode(
            {"query": title.strip(), "type": "search"})
        request = Request(url, headers={
            "X-Api-Key": self._credentials.api_key,
            "Accept": "application/json",
        })
        try:
            with self._open(request, timeout=self.options.timeout_seconds) as response:
                if response.status != 200:
                    raise ProwlarrUnavailable()
                raw = response.read(MAX_RESPONSE + 1)
        except HTTPError as exc:
            exc.close()
            if exc.code in (401, 403):
                raise ProwlarrAuthenticationError() from None
            raise ProwlarrUnavailable() from None
        except (OSError, TimeoutError, URLError):
            raise ProwlarrUnavailable() from None
        if len(raw) > MAX_RESPONSE:
            raise ProwlarrInvalidResponse()
        try:
            releases = json.loads(raw)
        except (ValueError, UnicodeError, RecursionError):
            raise ProwlarrInvalidResponse() from None
        if type(releases) is not list:
            raise ProwlarrInvalidResponse()
        # Do not silently truncate a response and pretend the search was complete.
        if len(releases) > MAX_RESULTS:
            raise ProwlarrInvalidResponse()
        return releases


def _episode(title, alias, season):
    """Port the legacy exact-alias prefix matching, not fuzzy title identity."""
    if (type(title) is not str or not 1 <= len(title) <= 1024
            or type(alias) is not str or not alias.strip() or len(alias) > 200):
        return None
    qualified = re.fullmatch(r"(.+?)\s+\[S(\d{2})\]", alias.strip(), re.I)
    if qualified and int(qualified.group(2)) != season:
        return None
    name = qualified.group(1) if qualified else alias.strip()
    prefix = re.escape(name)
    prefix = re.sub(r"(?:\\ |\\\.|\\_|\\-)+", r"[ ._-]+", prefix)
    stripped = re.sub(r"^\[[^\]]{1,80}\]\s*", "", title.strip())
    scoped = re.match(r"^" + prefix + r"[ ._-]+S(?P<s>\d{1,2})E(?P<e>\d{1,4})(?!\d)",
                      stripped, re.I)
    dashed = re.match(r"^" + prefix + r"\s+-\s+(?P<e>\d{1,4})(?:v\d+)?(?!\d)",
                      stripped, re.I)
    if not scoped and not dashed:
        return None
    if scoped and int(scoped.group("s")) != season:
        return None
    number = int((scoped or dashed).group("e"))
    return number if number > 0 else None


def _magnet(value):
    if (type(value) is not str or len(value) > 8192
            or any(ord(c) < 32 or ord(c) == 127 for c in value)):
        return None
    parsed = urlsplit(value)
    if parsed.scheme != "magnet" or parsed.netloc or parsed.fragment:
        return None
    xt = parse_qs(parsed.query).get("xt", [])
    if len(xt) != 1 or not xt[0].lower().startswith("urn:btih:"):
        return None
    digest = xt[0][9:].lower()
    return digest if BTIH.fullmatch(digest) else None


def candidates(releases, *, aliases, season, wanted_episodes):
    """Return one unambiguous magnet per requested episode, as advisory data.

    Caller must supply aliases from an independently verified series/season,
    plus the frozen NextGen Window and known provider episode coverage.
    """
    if (type(season) is not int or not 1 <= season <= 100
            or not isinstance(aliases, (tuple, list)) or not 1 <= len(aliases) <= 32
            or any(type(a) is not str or not a.strip() for a in aliases)
            or not isinstance(wanted_episodes, (set, frozenset, tuple, list))
            or any(type(n) is not int or not 1 <= n <= 9999 for n in wanted_episodes)
            or len(wanted_episodes) > 1000):
        raise ValueError("Verified episode scope required")
    wanted = set(wanted_episodes)
    if not isinstance(releases, list) or len(releases) > MAX_RESULTS:
        raise ValueError("Bounded Prowlarr search results required")
    per_episode = {}
    for release in releases:
        if type(release) is not dict or type(release.get("title")) is not str:
            continue
        title = release["title"]
        numbers = {_episode(title, a, season) for a in aliases}
        numbers.discard(None)
        if len(numbers) != 1:
            continue
        number = next(iter(numbers))
        if number not in wanted:
            continue
        magnet = release.get("magnetUrl") or release.get("magnet_url")
        digest = _magnet(magnet)
        if digest is None:
            continue
        seeders = release.get("seeders")
        score = seeders if type(seeders) is int and seeders >= 0 else 0
        per_episode.setdefault(number, {})[digest] = {
            "episode": number, "release_name": title, "info_hash": digest,
            "magnet_uri": magnet, "seeders": score,
        }
    selected = []
    for number, unique in sorted(per_episode.items()):
        ordered = sorted(unique.values(), key=lambda row: (-row["seeders"], row["info_hash"]))
        if len(ordered) > 1 and ordered[0]["seeders"] == ordered[1]["seeders"]:
            continue
        selected.append(ordered[0])
    return selected
