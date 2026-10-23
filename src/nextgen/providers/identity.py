"""AniDB-first resolver composed for identify_anime_job; no fuzzy approval."""
from collections import OrderedDict
import re
import threading

from src.nextgen.providers.http import Clients, Credentials, Options, json_object
from src.nextgen.providers.errors import ProviderInvalidResponse
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

    def identify(request,configuration,cancelled):
        if cancelled.is_set(): raise IdentityNotReady()
        actual_options = options(configuration) if callable(options) else options
        if type(actual_options) is not Options: raise ValueError("provider options required")
        secret = credentials()  # Capture once before contacting either provider.
        if type(secret) is not Credentials:
            from src.nextgen.providers.errors import ProviderAuthenticationFailed
            raise ProviderAuthenticationFailed()
        title = title_extractor(request)
        if type(title) is not str or len(title)>2048: raise IdentityNotReady()
        # The legacy parser removes season labels for candidate discovery.
        # Until release-to-part evidence is implemented, do not silently turn
        # an explicit S02/Season 2 label into an approval for the first entry.
        seasons = re.findall(r"(?i)(?:\bS|\bSeason[ ._-]*S?)([0-9]{1,2})(?![0-9])",title)
        if any(int(value)>1 for value in seasons): raise IdentityNotReady()
        aliases,_ = release_title(title)
        if not aliases: raise IdentityNotReady()
        database = configuration.value("storage.database_path")
        client = pool.get(database,actual_options)
        candidates = client.title_candidates(aliases)  # AniDB always comes first.
        if len(candidates)!=1: raise IdentityNotReady()
        aid = next(iter(candidates))
        if cancelled.is_set(): raise IdentityNotReady()
        anime = client.anime(aid)  # Independent ID-specific AniDB HTTP evidence.
        if not {norm(x) for x in anime["titles"]} & {norm(x) for x in candidates[aid]}:
            raise IdentityConflict()
        tid = client.mapping(aid)  # Explicit Anime-Lists relation, never guessed.
        if cancelled.is_set(): raise IdentityNotReady()
        tvdb = client.series(tid,secret)
        if tvdb["live"]: raise IdentityConflict()
        if not tvdb["animation"]: raise IdentityNotReady()
        if tvdb["anidb_ids"] and aid not in tvdb["anidb_ids"]: raise IdentityConflict()
        if not {norm(x) for x in anime["titles"]} & {norm(x) for x in tvdb["titles"]}:
            raise IdentityConflict()
        if cancelled.is_set(): raise IdentityNotReady()
        return {"schema_version":2,"anime":{"anidb_id":aid,"tvdb_series_id":tid,"title":anime["title"]},
                "episodes":[],"attributes":{}}

    async def resolve(request,configuration,cancelled):
        # Own blocking network/parsing through completion; cancellation retains
        # the job's maintenance admission until the thread has finished.
        return await blocking(identify,request,configuration,cancelled)

    return resolve
