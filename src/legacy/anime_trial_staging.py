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
from anime_series_naming import clean_series_name
import xml.etree.ElementTree as ET
from anime_staging_permissions import resolve_policy,apply_directory,apply_file

def staged_destination(trial_root, *, title, season, episode, suffix, english_title=None):
    """One path function shared by staging and interrupted-worker reconciliation."""
    if type(season) is not int or season<1 or type(episode) is not int or episode<1:
        raise ValueError("Invalid episode ordering")
    if suffix.lower() not in (".mkv",".mp4",".m4v",".avi"):
        raise ValueError("Unsupported media format")
    folder=clean_series_name(english_title if english_title is not None else title)
    return (Path(trial_root)/folder/("Season %02d"%season)/
            ("S%02dE%02d"%(season,episode)+suffix.lower()))

def stage_verified(source, trial_root, *, title, tvdb_id, season, episode, series_id, english_title=None, staged_owner="", staged_group=""):
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
    uid,gid=resolve_policy(staged_owner,staged_group)
    dest=staged_destination(root,title=title,english_title=english_title,
                            season=season,episode=episode,suffix=source.suffix)
    folder=dest.parent.parent
    # Inspect pre-existing paths before mkdir: refuse symlinks or conflicting NFO.
    if folder.is_symlink() or dest.parent.is_symlink():
        raise ValueError("Unsafe series directory")
    folder.mkdir(exist_ok=True)
    apply_directory(folder,gid=gid)
    nfo=folder/"tvshow.nfo"
    if nfo.is_symlink():
        raise ValueError("Unsafe series metadata")
    if nfo.is_file():
        try:
            ids=[item.text for item in ET.parse(nfo).getroot().findall("uniqueid")
                 if item.attrib.get("type")=="tvdb"]
        except ET.ParseError as exc:
            raise ValueError("Existing series metadata invalid") from exc
        if str(tvdb_id) not in ids:
            raise ValueError("English series folder belongs to another TVDB identity")
    season_dir=dest.parent
    season_dir.mkdir(exist_ok=True)
    apply_directory(season_dir,gid=gid)
    if season_dir.is_symlink():
        raise ValueError("Unsafe season directory")
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
        # A mkstemp file begins at 0600: set effective media permissions
        # before publishing the hard link (which shares the inode mode).
        apply_file(Path(tmp),uid=uid,gid=gid)
        # Exclusive creation prevents accidental overwrite of existing media.
        os.link(tmp,dest)
        os.unlink(tmp)
        try:
            write_series_nfo(folder,title=title,tvdb_id=tvdb_id,english_title=english_title)
            write_episode_nfo(dest,title=title,season=season,episode=episode,tvdb_id=tvdb_id,english_title=english_title)
        except Exception:
            # Metadata may be unavailable; the verified video must survive.
            pass
        # A newly written NFO is also created with restrictive tempfile mode.
        # Apply the same group policy when NFOs were successfully created.
        for metadata in (folder/"tvshow.nfo", dest.with_suffix(".nfo")):
            if metadata.exists() or metadata.is_symlink():
                apply_file(metadata,uid=uid,gid=gid)
        return dest
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)
