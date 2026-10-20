"""Stage verified media for Jellyfin without modifying the source.

The caller must verify series and episode identity and the completed source.
No Shoko VFS operations are performed.
"""
import os
import hashlib
import shutil
import tempfile
from pathlib import Path
from anime_trial_metadata import write_episode_nfo,write_series_nfo

def stage_verified(source, trial_root, *, title, tvdb_id, season, episode, series_id, english_title=None):
    source=Path(source)
    root=Path(trial_root)
    if source.is_symlink() or not source.is_file() or source.stat().st_size<=0:
        raise ValueError("Expected verified regular media file")
    if not root.is_dir() or root.is_symlink():
        raise ValueError("Trial root must already exist")
    if type(series_id) is not int or series_id<=0:
        raise ValueError("Invalid series identity")
    if type(season) is not int or season<=0 or type(episode) is not int or episode<=0:
        raise ValueError("Invalid episode ordering")
    if not str(tvdb_id).isdigit() or int(tvdb_id)<=0 or not isinstance(title,str) or not title.strip():
        raise ValueError("Missing series metadata")
    if source.suffix.lower() not in (".mkv",".mp4",".m4v",".avi"):
        raise ValueError("Unsupported media format")
    folder=root/("TVDB-"+str(int(tvdb_id))+"-S"+str(series_id))
    folder.mkdir(exist_ok=True)
    if folder.is_symlink():
        raise ValueError("Unsafe series directory")
    season_dir=folder/("Season %02d"%season)
    season_dir.mkdir(exist_ok=True)
    if season_dir.is_symlink():
        raise ValueError("Unsafe season directory")
    dest=season_dir/("S%02dE%02d"%(season,episode)+source.suffix.lower())
    if dest.exists() or dest.is_symlink():
        raise FileExistsError("Existing staged media requires manual reconciliation")
    fd,tmp=tempfile.mkstemp(prefix=".anime-stage-",suffix=".tmp",dir=season_dir)
    try:
        source_digest=hashlib.sha256()
        with os.fdopen(fd,"wb") as output, source.open("rb") as input_file:
            for chunk in iter(lambda: input_file.read(1024*1024),b""):
                source_digest.update(chunk)
                output.write(chunk)
            output.flush()
            os.fsync(output.fileno())
        staged_digest=hashlib.sha256()
        with open(tmp,"rb") as staged_file:
            for chunk in iter(lambda: staged_file.read(1024*1024),b""):
                staged_digest.update(chunk)
        if source_digest.digest()!=staged_digest.digest():
            raise ValueError("Staged media checksum differs from source")
        if source.stat().st_size!=Path(tmp).stat().st_size:
            raise ValueError("Media changed while staging")
        # A source modified in place during copying can retain its size.
        # Re-read it to ensure the source still matches the published bytes.
        current_source_digest=hashlib.sha256()
        with source.open("rb") as source_check:
            for chunk in iter(lambda: source_check.read(1024*1024),b""):
                current_source_digest.update(chunk)
        if current_source_digest.digest()!=staged_digest.digest():
            raise ValueError("Source changed during staging")
        # Exclusive creation prevents accidental overwrite of existing media.
        os.link(tmp,dest)
        os.unlink(tmp)
        try:
            write_series_nfo(folder,title=title,tvdb_id=tvdb_id,english_title=english_title)
            write_episode_nfo(dest,title=title,season=season,episode=episode,tvdb_id=tvdb_id,english_title=english_title)
        except Exception:
            # NFO is optional convenience metadata. Preserve playable media.
            # A later metadata repair can be performed without restaging.
            pass
        return dest
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
