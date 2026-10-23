"""Bounded trial selection intents. Following count includes the trigger."""
from dataclasses import dataclass

from src.nextgen.history import integer, MAX_INTEGER


class TrialConflict(ValueError):
    reason_code="TRIAL_PLAN_CONFLICT"
    def __init__(self):super().__init__("The trial plan needs review.")


@dataclass(frozen=True)
class Window:
    backfill_count: int = 6
    following_count: int = 1

    def __post_init__(self):
        for value in (self.backfill_count,self.following_count):
            if type(value) is not int or not 0<=value<=1000: raise ValueError("invalid trial episode count")

    def episodes(self, anchor):
        integer(anchor,positive=True)
        if self.following_count and anchor>MAX_INTEGER-self.following_count+1:
            raise TrialConflict()
        return tuple(sorted(set(range(1,self.backfill_count+1)) |
                            set(range(anchor,anchor+self.following_count))))


@dataclass(frozen=True)
class TrialSource:
    verification_id: int
    verification_job_id: int
    event_id: int
    anidb_id: int
    tvdb_series_id: int
    tvdb_season: int
    tvdb_episode: int

    def __post_init__(self):
        for value in (self.verification_id,self.verification_job_id,self.event_id,
                      self.anidb_id,self.tvdb_series_id,self.tvdb_episode):integer(value,positive=True)
        integer(self.tvdb_season)


@dataclass(frozen=True)
class TrialProposal:
    source: TrialSource
    window: Window
    configuration_revision: int

    def __post_init__(self):
        if type(self.source) is not TrialSource or type(self.window) is not Window: raise ValueError("invalid trial proposal")
        integer(self.configuration_revision,positive=True)
