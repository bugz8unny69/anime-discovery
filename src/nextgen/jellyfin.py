"""Jellyfin library scan request: independent from staging and Sonarr Keep.

A 2xx response means Jellyfin accepted a scan request. It is NOT proof that
the background scan finished, found the media, or matched its TVDB metadata.
"""
from dataclasses import dataclass, field
from urllib.error import HTTPError, URLError
from urllib.request import Request, ProxyHandler, HTTPRedirectHandler, build_opener

from src.nextgen.acquisition.settings import endpoint, DownloadConfigurationError


class JellyfinConfigurationInvalid(ValueError):
    reason_code="JELLYFIN_CONFIGURATION_INVALID"
    def __init__(self):
        super().__init__("Jellyfin address, timeout or private API credential is invalid.")


class JellyfinUnavailable(RuntimeError):
    reason_code="JELLYFIN_REFRESH_UNAVAILABLE"
    def __init__(self):
        super().__init__("Jellyfin did not acknowledge the library scan request.")


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, repr=False)
class JellyfinOptions:
    base_url: str
    api_key: str=field(repr=False)
    timeout_seconds: int=15

    def __post_init__(self):
        try:
            normalized=endpoint(self.base_url)
        except DownloadConfigurationError:
            raise JellyfinConfigurationInvalid() from None
        if (type(self.api_key) is not str or not 8<=len(self.api_key)<=256
                or not self.api_key.isascii() or any(not (c.isalnum() or c in "-_") for c in self.api_key)
                or type(self.timeout_seconds) is not int or not 1<=self.timeout_seconds<=60):
            raise JellyfinConfigurationInvalid()
        object.__setattr__(self,"base_url",normalized)


class JellyfinClient:
    def __init__(self,options,*,opener=None):
        if type(options) is not JellyfinOptions:raise JellyfinConfigurationInvalid()
        self.options=options
        self._open=opener or build_opener(ProxyHandler({}),_NoRedirect()).open

    def request_scan(self):
        """POST /Library/Refresh once for the source event (safe if retried).

        There is no path/body input from the webhook, browser or job payload.
        API tokens are never placed in URLs, SQLite, history or error messages.
        """
        request=Request(self.options.base_url+"/Library/Refresh",method="POST",
                        headers={"Authorization":'MediaBrowser Token="'+self.options.api_key+'"',
                                 "Accept":"application/json"})
        try:
            with self._open(request,timeout=self.options.timeout_seconds) as response:
                if response.status not in (200,202,204):
                    raise JellyfinUnavailable()
                # Scan requests should not return media or meaningful JSON.
                if len(response.read(4097))>4096:raise JellyfinUnavailable()
        except HTTPError as exc:
            if exc.code in (400,401,403,404):
                raise JellyfinConfigurationInvalid() from None
            raise JellyfinUnavailable() from None
        except (URLError,OSError,TimeoutError,ValueError):
            raise JellyfinUnavailable() from None
