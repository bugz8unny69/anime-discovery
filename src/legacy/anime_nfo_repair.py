"""Repair optional Jellyfin NFO files for already staged media.

No media copying, torrent operations or deletion. Explicit maintenance only.
"""
from pathlib import Path
from anime_trial_metadata import write_episode_nfo,write_series_nfo

def repair_nfo(staged_path, *, title, tvdb_id, season, episode):
    staged=Path(staged_path)
    if staged.is_symlink() or not staged.is_file():
        raise ValueError("Staged media missing or unsafe")
    if type(season) is not int or season<1 or type(episode) is not int or episode<1:
        raise ValueError("Invalid episode")
    if not isinstance(title,str) or not title.strip() or not str(tvdb_id).isdigit() or int(tvdb_id)<1:
        raise ValueError("Invalid series metadata")
    season_dir=staged.parent
    series_dir=season_dir.parent
    if season_dir.is_symlink() or series_dir.is_symlink():
        raise ValueError("Unsafe metadata directory")
    write_series_nfo(series_dir,title=title,tvdb_id=tvdb_id)
    write_episode_nfo(staged,title=title,season=season,episode=episode,tvdb_id=tvdb_id)
    return {"media_preserved":True,"metadata_repaired":True}
