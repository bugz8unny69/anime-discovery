"""Immutable declared-episode verification facts; no acquisition authorization."""
from dataclasses import dataclass, field
import hashlib

from src.nextgen.history import integer


class ReleaseNotReady(ValueError):
    reason_code = "RELEASE_UNRESOLVED"
    def __init__(self):
        super().__init__("The release's episode coverage needs review.")


class ReleaseConflict(ValueError):
    reason_code = "RELEASE_CONFLICT"
    def __init__(self):
        super().__init__("Release episode information conflicts.")


@dataclass(frozen=True)
class ReleaseInput:
    event_id: int
    identity_result_id: int
    anidb_id: int
    tvdb_series_id: int
    raw_body: bytes = field(repr=False)

    def __post_init__(self):
        for value in (self.event_id,self.identity_result_id,self.anidb_id,self.tvdb_series_id):
            integer(value,positive=True)
        if type(self.raw_body) is not bytes or not 1<=len(self.raw_body)<=65536:
            raise ReleaseNotReady()

    @property
    def release_sha256(self):
        return hashlib.sha256(self.raw_body).hexdigest()


@dataclass(frozen=True)
class VerifiedRelease:
    source: ReleaseInput = field(repr=False)
    anidb_episode_number: int
    anidb_episode_id: int
    tvdb_season: int
    tvdb_episode: int
    tvdb_episode_id: int

    def __post_init__(self):
        if type(self.source) is not ReleaseInput: raise ValueError("release source required")
        for value in (self.anidb_episode_number,self.anidb_episode_id,self.tvdb_episode,self.tvdb_episode_id):
            integer(value,positive=True)
        integer(self.tvdb_season)
