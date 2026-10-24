"""Reuse staged output and both provider identities for Keep; no Shoko dependency."""
from dataclasses import dataclass, field
import json
from pathlib import PurePosixPath

from src.nextgen.history import integer
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.review_decisions import staged, require_allowed


class KeepSelectionInvalid(ValueError):
    def __init__(self):super().__init__('The staged episode could not be matched to its verified TVDB placement.')


@dataclass(frozen=True)
class KeepSelection:
    anidb_id: int
    anidb_episode_id: int
    tvdb_series_id: int
    tvdb_episode_id: int
    tvdb_season: int
    tvdb_episode: int
    preparation_plan_id: int
    staging_root: str = field(repr=False)
    media_relative_path: str = field(repr=False)

    def __post_init__(self):
        for name in ('anidb_id','anidb_episode_id','tvdb_series_id','tvdb_episode_id','tvdb_episode','preparation_plan_id'):
            integer(getattr(self,name),positive=True)
        integer(self.tvdb_season)
        from src.nextgen.acquisition.metadata import safe_path
        safe_path(self.media_relative_path)
        if not PurePosixPath(self.staging_root).is_absolute():raise KeepSelectionInvalid()

    @property
    def media_path(self):return str(PurePosixPath(self.staging_root)/self.media_relative_path)

    def match_sonarr_episode(self,series,episodes):
        """TVDB mapping is authoritative; titles/AniDB/Shoko do not pick a series."""
        if type(series) is not dict or type(episodes) is not list:raise KeepSelectionInvalid()
        if type(series.get('tvdbId')) is not int or series['tvdbId']!=self.tvdb_series_id:raise KeepSelectionInvalid()
        try:series_id=integer(series['id'],positive=True)
        except (ValueError,KeyError):raise KeepSelectionInvalid() from None
        matches=[row for row in episodes if type(row) is dict and row.get('seriesId')==series_id
                 and type(row.get('seasonNumber')) is int and row['seasonNumber']==self.tvdb_season
                 and type(row.get('episodeNumber')) is int and row['episodeNumber']==self.tvdb_episode]
        if len(matches)!=1:raise KeepSelectionInvalid()
        match=matches[0]
        try:episode_id=integer(match['id'],positive=True)
        except (ValueError,KeyError):raise KeepSelectionInvalid() from None
        if match.get('tvdbId') not in (None,0,self.tvdb_episode_id):raise KeepSelectionInvalid()
        return series_id,episode_id


def load_selection(db,target_job_id):
    """Read the existing staged manifest, rather than rebuilding names or NFOs."""
    op=operation(db,target_job_id)
    if op[1]!='STAGED':raise KeepSelectionInvalid()
    source=staged(db,op[0]);require_allowed(db,source[0])
    identity=db.execute('SELECT r.anidb_id,r.anidb_episode_id,r.tvdb_series_id,r.tvdb_episode_id,r.tvdb_season,r.tvdb_episode '
        'FROM acquisition_plans p JOIN episode_reservations r USING(reservation_id) WHERE p.plan_id=?',(source[1],)).fetchone()
    if identity is None:raise KeepSelectionInvalid()
    manifest=json.loads(source[2]);receipts=json.loads(source[3])
    media=[entry for entry in manifest['entries'] if entry['role']=='media']
    proof=[entry for entry in receipts if entry['role']=='media']
    if len(media)!=1 or len(proof)!=1 or media[0]['path']!=proof[0]['path']:raise KeepSelectionInvalid()
    return KeepSelection(*identity,source[1],manifest['root'],media[0]['path'])
