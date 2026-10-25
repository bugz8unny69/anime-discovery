"""AniDB-first resolver composed for identify_anime_job; no fuzzy approval."""
from collections import OrderedDict
import re
import threading
from contextlib import closing
from src.nextgen.storage.recognition import recognized_for_release
from src.nextgen.storage.migrations import _open, LATEST_VERSION

from src.nextgen.providers.http import Clients, Credentials, Options, json_object
from src.nextgen.providers.errors import (ProviderInvalidResponse, ProviderDeferred,
    ProviderUnavailable, ProviderAuthenticationFailed)
from src.nextgen.providers.parsing import norm, release_title
from src.nextgen.storage.sqlite import IdentityConflict, IdentityNotReady
from src.nextgen.worker import blocking


def delivery_title(request):
    """Initial explicit JSON input contract; future intake adapters normalize it."""
    if type(request.raw_body) is not bytes or len(request.raw_body)>65536:
        raise IdentityNotReady()
    try:
        document = json_object(request.raw_body)
    except ProviderInvalidResponse:
        raise IdentityNotReady() from None
    value = document.get("release_name")
    if type(value) is not str or not value.strip() or len(value)>2048:
        raise IdentityNotReady()
    if any(ord(char)<32 or ord(char)==127 for char in value): raise IdentityNotReady()
    return value


class ClientPool:
    """Share bounded option-specific clients across identity and release jobs."""
    def __init__(self, factory=Clients):
        self.factory,self.clients,self.lock=factory,OrderedDict(),threading.Lock()

    def get(self, database, options):
        if type(options) is not Options: raise ValueError("provider options required")
        with self.lock:
            if any(key[0]!=database for key in self.clients):
                raise ValueError("resolver database changed; rebuild composition")
            key=(database,options)
            client=self.clients.get(key)
            if client is None: client=self.clients[key]=self.factory(database,options)
            self.clients.move_to_end(key)
            while len(self.clients)>4: self.clients.popitem(last=False)
            return client


def make_resolver(options, credentials, *, title_extractor=delivery_title, client_factory=Clients, client_pool=None):
    """Return an async resolver with shared clients/caches for all its attempts.

    Options are trusted service composition, not undocumented settings keys.
    credentials() must return Credentials from the service secret facility;
    neither it nor any API key is read from a webhook or public configuration.
    title_extractor is a trusted normalizer, never a payload-selected callable.
    """
    if (type(options) is not Options and not callable(options)) or not callable(credentials) or not callable(title_extractor):
        raise ValueError("provider composition is incomplete")
    pool = client_pool or ClientPool(client_factory)

    def identify(request, configuration, cancelled, matching=None):
        # One trace per attempted job. Never use trace content to authorize identity.
        stage = "release_title"

        def check(step, status, note=None):
            if matching is not None:
                matching.check(step, status, note)

        def incomplete(note):
            check(stage, "failed", note)
            raise IdentityNotReady()

        try:
            if cancelled.is_set():
                incomplete("canceled")
            actual_options = options(configuration) if callable(options) else options
            if type(actual_options) is not Options:
                raise ValueError("provider options required")
            secret = credentials()
            if type(secret) is not Credentials:
                from src.nextgen.providers.errors import ProviderAuthenticationFailed
                raise ProviderAuthenticationFailed()
            title = title_extractor(request)
            if type(title) is not str or len(title) > 2048:
                incomplete("invalid_release_title")
            seasons = re.findall(r"(?i)(?:\bS|\bSeason[ ._-]*S?)([0-9]{1,2})(?![0-9])", title)
            aliases, episode = release_title(title)
            if matching is not None:
                matching.queries(aliases, episode, int(seasons[0]) if len(seasons) == 1 else None)
            if len({int(value) for value in seasons}) > 1:
                stage = "season_scope"
                incomplete("multiple_seasons")
            if not aliases:
                incomplete("no_title_aliases")
            check("release_title", "passed")

            # First reuse existing season-scoped *verified* observations only.
            database = configuration.value("storage.database_path")
            stage = "recognized_season"
            if seasons:
                with closing(_open(database, readonly=True, timeout_ms=5000)) as known_db:
                    if known_db.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION:
                        known = recognized_for_release(known_db, title, season=int(seasons[0]))
                        if known is not None:
                            if matching is not None:
                                matching.anidb(known["anidb_id"])
                                matching.tvdb(known["tvdb_series_id"], (known["title"],))
                            check(stage, "passed", "recognized_season_reused")
                            check("identity_verified", "passed", "verified")
                            return {"schema_version": 2, "anime": {
                                "anidb_id": known["anidb_id"],
                                "tvdb_series_id": known["tvdb_series_id"],
                                "title": known["title"]}, "episodes": [], "attributes": {}}
                check(stage, "failed", "not_previously_recognized")
            else:
                check(stage, "skipped")

            # An unfamiliar sequel must not be assigned the first AniDB work.
            # Later season-aware evidence can add trusted discovery here.
            stage = "season_scope"
            if any(int(value) > 1 for value in seasons):
                incomplete("unverified_sequel")
            check(stage, "passed" if seasons else "skipped")

            stage = "anidb_candidates"
            client = pool.get(database, actual_options)
            candidates = client.title_candidates(aliases)
            if matching is not None:
                matching.candidates(candidates)
            if len(candidates) != 1:
                incomplete("no_unique_anidb_candidate")
            check(stage, "passed")
            aid = next(iter(candidates))
            if matching is not None:
                matching.anidb(aid)

            if cancelled.is_set():
                incomplete("canceled")
            stage = "anidb_record"
            anime = client.anime(aid)
            if not {norm(x) for x in anime["titles"]} & {norm(x) for x in candidates[aid]}:
                check(stage, "failed", "anidb_titles_disagree")
                raise IdentityConflict()
            check(stage, "passed")

            stage = "anime_lists"
            tid = client.mapping(aid)
            if matching is not None:
                matching.tvdb(tid, ())
            check(stage, "passed")
            if cancelled.is_set():
                incomplete("canceled")

            stage = "tvdb_series"
            tvdb = client.series(tid, secret)
            if matching is not None:
                matching.tvdb(tid, tvdb["titles"])
            check(stage, "passed")
            if tvdb["live"]:
                check("tvdb_animation", "failed", "tvdb_live_action")
                raise IdentityConflict()
            if not tvdb["animation"]:
                stage = "tvdb_animation"
                incomplete("tvdb_not_animation")
            check("tvdb_animation", "passed")

            stage = "provider_link"
            if tvdb["anidb_ids"] and aid not in tvdb["anidb_ids"]:
                check(stage, "failed", "tvdb_anidb_conflict")
                raise IdentityConflict()
            check(stage, "passed")
            stage = "provider_titles"
            if not {norm(x) for x in anime["titles"]} & {norm(x) for x in tvdb["titles"]}:
                check(stage, "failed", "provider_titles_disagree")
                raise IdentityConflict()
            check(stage, "passed")
            if cancelled.is_set():
                incomplete("canceled")
            check("identity_verified", "passed", "verified")
            return {"schema_version": 2, "anime": {
                "anidb_id": aid, "tvdb_series_id": tid, "title": anime["title"]},
                "episodes": [], "attributes": {}}
        except ProviderDeferred:
            check(stage, "waiting", "upstream_deferred")
            raise
        except ProviderUnavailable:
            check(stage, "waiting", "upstream_unavailable")
            raise
        except ProviderInvalidResponse:
            check(stage, "failed", "invalid_provider_response")
            raise
        except IdentityNotReady:
            if matching is not None and not any(
                    check["step"] == stage and check["status"] == "failed"
                    for check in matching.data["checks"]):
                check(stage, "failed", "missing_verification")
            raise
        except IdentityConflict:
            if matching is not None and not any(
                    check["step"] == stage and check["status"] == "failed"
                    for check in matching.data["checks"]):
                check(stage, "failed", "identity_conflict")
            raise

    async def resolve(request, configuration, cancelled, *, matching=None):
        return await blocking(identify, request, configuration, cancelled, matching)

    return resolve
