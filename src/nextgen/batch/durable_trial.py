"""Read-only selection of provider-verified batch episodes into a durable trial plan.

No episode reservation, download permit, torrent selection, or Keep authority.
"""
from dataclasses import dataclass

from src.nextgen.acquisition.settings import SizeLimits
from src.nextgen.history import integer
from src.nextgen.trial_policy import Window, TrialConflict


@dataclass(frozen=True)
class BatchEpisodeFact:
    file_index: int
    release_episode: int
    anidb_episode_id: int
    tvdb_episode: int
    tvdb_episode_id: int
    size_bytes: int

    def __post_init__(self):
        for value in (self.release_episode,self.anidb_episode_id,self.tvdb_episode,
                      self.tvdb_episode_id,self.size_bytes):
            integer(value,positive=True)
        integer(self.file_index)


@dataclass(frozen=True)
class BatchTrialSource:
    verification_job_id: int
    event_id: int
    batch_id: int
    anidb_id: int
    tvdb_series_id: int
    season: int
    episodes: tuple[BatchEpisodeFact,...]

    def __post_init__(self):
        for value in (self.verification_job_id,self.event_id,self.batch_id,
                      self.anidb_id,self.tvdb_series_id,self.season):
            integer(value,positive=True)
        if type(self.episodes) is not tuple or not self.episodes or len(self.episodes)>10000:
            raise TrialConflict()
        if any(type(x) is not BatchEpisodeFact for x in self.episodes):
            raise TrialConflict()
        if any(len({getattr(x,field) for x in self.episodes})!=len(self.episodes)
               for field in ('file_index','release_episode','anidb_episode_id',
                             'tvdb_episode','tvdb_episode_id')):
            raise TrialConflict()


@dataclass(frozen=True)
class BatchTrialProposal:
    source: BatchTrialSource
    window: Window
    limits: SizeLimits
    configuration_revision: int
    anchor_episode: int
    selected: tuple[BatchEpisodeFact,...]

    def __post_init__(self):
        if type(self.source) is not BatchTrialSource or type(self.window) is not Window or type(self.limits) is not SizeLimits:
            raise TrialConflict()
        integer(self.configuration_revision,positive=True)
        integer(self.anchor_episode,positive=True)
        allowed=set(self.window.episodes(self.anchor_episode))
        expected=tuple(sorted((x for x in self.source.episodes if x.tvdb_episode in allowed),
                              key=lambda x:(x.tvdb_episode,x.file_index)))
        if not expected or expected != self.selected:
            raise TrialConflict()
        total=0
        for item in self.selected:
            self.limits.admit(item.size_bytes,total)
            total+=item.size_bytes


def propose_batch_trial(source,window,limits,revision):
    """The season pack has no webhook episode anchor: require E01 explicitly."""
    if type(source) is not BatchTrialSource:
        raise TrialConflict()
    if 1 not in {x.tvdb_episode for x in source.episodes}:
        raise TrialConflict()
    selected=tuple(sorted((x for x in source.episodes
                           if x.tvdb_episode in set(window.episodes(1))),
                          key=lambda x:(x.tvdb_episode,x.file_index)))
    return BatchTrialProposal(source,window,limits,revision,1,selected)
