"""Verify one declared regular episode using AniDB, explicit mapping and TVDB."""
from src.nextgen.providers.errors import ProviderInvalidResponse, ProviderAuthenticationFailed
from src.nextgen.providers.http import Clients, Credentials, Options
from src.nextgen.providers.identity import ClientPool, delivery_title
from src.nextgen.providers.release_mapping import declared_episode, forward_mappings
from src.nextgen.release_contracts import VerifiedRelease, ReleaseNotReady, ReleaseConflict
from src.nextgen.worker import blocking


def make_verifier(options, credentials, *, client_pool=None, client_factory=Clients):
    if (type(options) is not Options and not callable(options)) or not callable(credentials):
        raise ValueError("release provider composition is incomplete")
    pool=client_pool or ClientPool(client_factory)

    def verify(source,configuration,cancelled):
        if cancelled.is_set(): raise ReleaseNotReady()
        actual=options(configuration) if callable(options) else options
        secret=credentials()
        if type(secret) is not Credentials: raise ProviderAuthenticationFailed()
        try: title=delivery_title(source)
        except ValueError: raise ReleaseNotReady() from None
        origin,season,number=declared_episode(title)
        client=pool.get(configuration.value("storage.database_path"),actual)
        catalog=client.episodes(source.anidb_id)
        mappings=forward_mappings(client.mapping_xml(),source.anidb_id,source.tvdb_series_id,catalog)
        if origin=="anidb":
            if number not in catalog or number not in mappings: raise ReleaseNotReady()
            target=mappings[number]
        else:
            candidates=[n for n,target in mappings.items() if target==(season,number)]
            if len(candidates)!=1: raise ReleaseNotReady()
            number=candidates[0]
            target=mappings[number]
        # Detect merged mappings even in the forward case. A single declared
        # episode never authorizes an ambiguous split/merged coverage assertion.
        if sum(value==target for value in mappings.values())!=1: raise ReleaseConflict()
        seen=set()
        matches=[]
        total=0
        for page in range(20):
            if cancelled.is_set(): raise ReleaseNotReady()
            records,has_next=client.episode_page(source.tvdb_series_id,page,secret)
            total+=len(records)
            if total>10000: raise ProviderInvalidResponse()
            for eid,record_season,record_number in records:
                if eid in seen: raise ProviderInvalidResponse()
                seen.add(eid)
                if (record_season,record_number)==target: matches.append(eid)
            if not has_next: break
        else: raise ProviderInvalidResponse()
        if not matches: raise ReleaseNotReady()
        if len(matches)!=1: raise ReleaseConflict()
        if cancelled.is_set(): raise ReleaseNotReady()
        return VerifiedRelease(source,number,catalog[number],target[0],target[1],matches[0])

    async def call(source,configuration,cancelled):
        return await blocking(verify,source,configuration,cancelled)
    return call
