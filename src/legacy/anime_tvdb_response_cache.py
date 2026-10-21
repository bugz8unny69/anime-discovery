"""Bounded, process-local TVDB response cache for the identity worker.

Cache entries are scoped to worker metadata DB and authorization fingerprint.
No authentication secrets or provider responses are persisted to disk.
"""
import copy
import hashlib
import time
from collections import OrderedDict

SERIES_TTL=900
EPISODES_TTL=300
TOKEN_TTL=1800
MAX_ENTRIES=128
_entries=OrderedDict()

def fingerprint(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()

def cache_get(scope,kind,key,*,now=None):
    stamp=time.time() if now is None else now
    cachekey=(str(scope),kind,key)
    entry=_entries.get(cachekey)
    if entry is None:
        return None
    expiry,value=entry
    if not 0<=expiry-stamp:
        _entries.pop(cachekey,None)
        return None
    _entries.move_to_end(cachekey)
    return copy.deepcopy(value)

def cache_put(scope,kind,key,value,*,now=None):
    stamp=time.time() if now is None else now
    ttl={"token":TOKEN_TTL,"series":SERIES_TTL,"episodes":EPISODES_TTL}.get(kind)
    if ttl is None:
        raise ValueError("Unrecognized TVDB cache kind")
    cachekey=(str(scope),kind,key)
    _entries[cachekey]=(stamp+ttl,copy.deepcopy(value))
    _entries.move_to_end(cachekey)
    while len(_entries)>MAX_ENTRIES:
        _entries.popitem(last=False)

def cache_forget(scope,kind,key):
    _entries.pop((str(scope),kind,key),None)

