"""Exact-episode reservation facts; no torrent ownership or external authority."""
from dataclasses import dataclass
from src.nextgen.history import integer


class ReservationConflict(ValueError):
    reason_code = 'EPISODE_RESERVATION_CONFLICT'
    def __init__(self):
        super().__init__('Episode reservation details need review.')


class EpisodeStaged(ValueError):
    """Exact verified episode has already been published into staging."""


class EpisodeReserved(ValueError):
    reason_code = 'EPISODE_RESERVED'
    def __init__(self):
        super().__init__('Another job has reserved this episode.')


@dataclass(frozen=True)
class ReservationInput:
    evaluation_job_id: int
    event_id: int
    verification_id: int
    plan_id: int
    anidb_id: int
    anidb_episode_id: int
    tvdb_series_id: int
    tvdb_season: int
    tvdb_episode: int
    tvdb_episode_id: int
    selected: bool

    def __post_init__(self):
        for name in ('evaluation_job_id','event_id','verification_id','plan_id','anidb_id',
                     'anidb_episode_id','tvdb_series_id','tvdb_episode','tvdb_episode_id'):
            integer(getattr(self,name),positive=True)
        integer(self.tvdb_season)
        if type(self.selected) is not bool:raise ValueError('invalid episode selection')
