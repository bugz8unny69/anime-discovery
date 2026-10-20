"""Write minimal Jellyfin/Kodi-style local NFO metadata for staged episodes.

Only caller-verified identity may be supplied. Files are atomically replaced;
this module never moves media, invokes Jellyfin, or modifies Shoko VFS.
"""
from pathlib import Path
import os
import tempfile
import xml.etree.ElementTree as ET


def _write_xml(path, root):
    path=Path(path)
    if path.is_symlink():
        raise ValueError("Refusing symlink metadata target")
    data=ET.tostring(root,encoding="utf-8",xml_declaration=True)
    fd,name=tempfile.mkstemp(prefix=".anime-nfo-",suffix=".tmp",dir=path.parent)
    try:
        with os.fdopen(fd,"wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name,path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _display_title(title, english_title):
    """Only an explicitly supplied English title may override the canonical title."""
    if isinstance(english_title, str) and english_title.strip():
        return english_title.strip()
    return title


def write_episode_nfo(video_path, *, title, season, episode, tvdb_id, episode_title=None, english_title=None):
    video=Path(video_path)
    if not video.is_file() or video.is_symlink():
        raise ValueError("Expected existing regular video file")
    if not isinstance(season,int) or not isinstance(episode,int) or season<0 or episode<1:
        raise ValueError("Invalid verified episode ordering")
    if not str(tvdb_id).isdigit() or not title or not title.strip():
        raise ValueError("Missing verified series metadata")
    root=ET.Element("episodedetails")
    ET.SubElement(root,"title").text=episode_title or f"Episode {episode}"
    ET.SubElement(root,"showtitle").text=_display_title(title,english_title)
    ET.SubElement(root,"season").text=str(season)
    ET.SubElement(root,"episode").text=str(episode)
    ET.SubElement(root,"uniqueid",{"type":"tvdb","default":"true"}).text=str(tvdb_id)
    dest=video.with_suffix(".nfo")
    _write_xml(dest,root)
    return dest


def write_series_nfo(series_directory, *, title, tvdb_id, anidb_id=None, english_title=None):
    folder=Path(series_directory)
    if not folder.is_dir() or folder.is_symlink():
        raise ValueError("Expected existing series directory")
    if not title or not title.strip() or not str(tvdb_id).isdigit():
        raise ValueError("Missing verified series identity")
    root=ET.Element("tvshow")
    ET.SubElement(root,"title").text=_display_title(title,english_title)
    ET.SubElement(root,"uniqueid",{"type":"tvdb","default":"true"}).text=str(tvdb_id)
    if anidb_id is not None:
        if not str(anidb_id).isdigit():
            raise ValueError("Invalid AniDB ID")
        ET.SubElement(root,"uniqueid",{"type":"anidb"}).text=str(anidb_id)
    dest=folder/"tvshow.nfo"
    _write_xml(dest,root)
    return dest
