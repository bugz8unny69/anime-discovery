"""Choose a trustworthy, filesystem-safe English series folder name.

Never use raw torrent release names as directory names. Prefer verified TVDB
English translation, then a uniquely configured TVDB-matched alias, then an
already-clean persisted series name. Refuse to stage if none is available.
"""
import re
import unicodedata

_BAD_COMPONENT=re.compile(r'[<>:"/\\|?*\x00-\x1f\x7f]')
_RELEASE_TOKENS=re.compile(
    r'(?i)(?:\bS\d{1,2}E\d{1,3}\b|\b\d{3,4}p\b|\b(?:WEB[- .]?DL|BluRay|HEVC|x264|x265)\b|'
    r'\.(?:mkv|mp4|avi)$|^\s*\[|\s-\s(?:EP?\s*)?\d{1,3}(?:\s|$))')

def clean_series_name(value):
    if not isinstance(value,str):
        raise ValueError("English series name required")
    name=unicodedata.normalize("NFKC",value)
    name=_BAD_COMPONENT.sub(" ",name)
    name=" ".join(name.split()).strip(" .")
    if (not name or name in (".","..") or len(name)>160 or
            _RELEASE_TOKENS.search(name) or name.casefold().startswith("tvdb-")):
        raise ValueError("English series name is not a safe clean series title")
    return name

def resolve_series_name(db, series_id, tvdb_id, *, english_title=None, series_map=None):
    """Select a verified English name without ever trusting the release label."""
    row=db.execute("""SELECT title,external_id,source FROM series
        WHERE id=?""",(series_id,)).fetchone()
    if not row or row[2]!="tvdb" or str(row[1])!=str(tvdb_id):
        raise ValueError("Verified series identity mismatch")
    candidates=[]
    if english_title is not None:
        candidates.append(english_title)
    if isinstance(series_map,dict):
        aliases=[key for key,value in series_map.items()
                 if isinstance(value,dict) and str(value.get("tvdb_id"))==str(tvdb_id)]
        clean_aliases=set()
        for alias in aliases:
            try:
                clean_aliases.add(clean_series_name(alias))
            except ValueError:
                continue
        if len(clean_aliases)==1:
            candidates.extend(clean_aliases)
    candidates.append(row[0])
    for candidate in candidates:
        try:
            name=clean_series_name(candidate)
        except ValueError:
            continue
        # Refuse two different verified TVDB series with the same display path.
        conflict=db.execute("""SELECT 1 FROM series
            WHERE id!=? AND source='tvdb' AND external_id!=?
            AND title=? LIMIT 1""",(series_id,str(tvdb_id),name)).fetchone()
        if conflict:
            raise ValueError("Series title collision with another TVDB series")
        return name
    raise ValueError("English series name unavailable; configure a unique recognized name or TVDB translation")
