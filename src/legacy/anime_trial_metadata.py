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



def tvdb_english_title(tvdb_id, api_key, *, login=None, fetch=None):
    """Read the TVDB English translation for an already verified series ID.

    Metadata-only best effort; never affects identity approval or acquisition.
    """
    if not api_key or not str(tvdb_id).isdigit() or int(tvdb_id) <= 0:
        return None
    from anime_identity_verify import TVDB_URL, tvdb_token, request_json
    login = login or tvdb_token
    fetch = fetch or request_json
    try:
        token = login(api_key)
        record = fetch(TVDB_URL + "/series/" + str(int(tvdb_id)) +
                       "/translations/eng", bearer=token).get("data")
        if not isinstance(record, dict):
            return None
        title = record.get("name")
        if (not isinstance(title, str) or not title.strip() or
                len(title) > 180 or not all(c.isprintable() for c in title)):
            return None
        return title.strip()
    except Exception:
        # Jellyfin NFO translations are optional: do not block staged media.
        return None

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
