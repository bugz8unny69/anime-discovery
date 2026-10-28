"""Conservative declared-episode parsing and explicit Anime-Lists mapping.

Adapted from legacy release_identity/anime_identity_mapping_v4. No trial-window,
season-one policy, filename authority, unsupported split mapping or inferred
episode placement beyond Anime-Lists' documented zero-offset defaults.
"""
import re

from src.nextgen.providers.parsing import xml
from src.nextgen.release_contracts import ReleaseNotReady, ReleaseConflict


def declared_episode(title):
    if type(title) is not str or not 1<=len(title)<=2048: raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
    if re.search(r"\b(?:batch|complete|pack|ova|oav|ona|specials?|ncop|nced|pv|trailer|movie|recap|extras?)\b",title,re.I):
        raise ReleaseNotReady("RELEASE_TYPE_UNSUPPORTED")
    if re.search(r"\d\s*(?:-|~|&|\+|,)\s*(?:E(?:P)?\s*)?\d",title,re.I):
        raise ReleaseNotReady("RELEASE_TYPE_UNSUPPORTED")
    boundary=r"(?=$|[\s\[\]()_.-]|v[0-9]+\b)"
    explicit_pattern=r"(?<![A-Za-z0-9])S(\d{1,2})[ ._-]*E(\d{1,4})"+boundary
    explicit=list(re.finditer(explicit_pattern,title,re.I))
    rest=re.sub(explicit_pattern," ",title,flags=re.I)
    ordinary=list(re.finditer(r"(?<![A-Za-z0-9])(?:Episode\s*|EP\.?\s*|E\s*|-\s*)(\d{1,4})"+boundary,rest,re.I))
    if re.search(r"(?:\b(?:EP(?:ISODE)?|E)\s*-|--|-[ \t]+-)\s*[0-9]",title,re.I):
        raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
    if re.search(r"(?:EP(?:ISODE)?|E)\s*[0-9]{1,4}(?:EP(?:ISODE)?|E)\s*[0-9]",title,re.I) or re.search(r"(?:Episode\s*|EP\.?\s*|E\s*|-\s*)[0-9]+\.[0-9]",title,re.I):
        raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
    if len(explicit)+len(ordinary)!=1: raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
    if explicit:
        season,number = map(int,explicit[0].groups())
        if re.search(r"\b(?:Season\s*\d+|S\d{1,2})\b",rest,re.I): raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
        if number<1: raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
        return "tvdb",season,number
    if re.search(r"\b(?:Season\s*\d+|S\d{1,2})\b",rest,re.I): raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
    number=int(ordinary[0].group(1))
    if number<1: raise ReleaseNotReady("RELEASE_TITLE_UNCLEAR")
    return "anidb",None,number


def forward_mappings(payload, aid, tid, catalog):
    """Resolve regular AniDB numbers through supported explicit mapping rules.

    Anime-Lists defines omitted/blank offsets as zero when episode numbers
    align. A mapped TVDB season and authoritative episode catalog are still
    required. Unknown/split/absolute rules fail closed.
    """
    root=xml(payload,"anime-list",limit=16777216)
    rows=[node for node in root.findall("anime") if node.get("anidbid")==str(aid)]
    if len(rows)!=1: raise ReleaseNotReady("RELEASE_MAPPING_MISSING")
    node=rows[0]
    if node.get("tvdbid")!=str(tid): raise ReleaseConflict()
    rules=[]
    for item in node.findall("mapping-list/mapping"):
        if item.get("anidbseason")!="1": continue
        # Anime-Lists also contains TMDB-only mappings; those are not TVDB rules.
        season=item.get("tvdbseason")
        if season is None: continue
        if not re.fullmatch(r"[0-9]{1,3}",season): raise ReleaseNotReady("RELEASE_MAPPING_UNSUPPORTED")
        target_season=int(season)
        text=(item.text or "").strip()
        for token in text.strip(";").split(";") if text else ():
            if not token: continue
            match=re.fullmatch(r"([1-9][0-9]{0,3})-([1-9][0-9]{0,3})",token.strip())
            if not match: raise ReleaseNotReady("RELEASE_MAPPING_UNSUPPORTED")
            source,target=map(int,match.groups())
            rules.append((2,source,source,target_season,target-source))
        start,end=item.get("start"),item.get("end")
        if start is not None or end is not None:
            offset=item.get("offset") or "0"
            # An omitted end means the range continues through later AniDB episodes.
            # Resolve only against episode numbers present in the AniDB catalog.
            last=end if end is not None else "9999"
            if (not re.fullmatch(r"[1-9][0-9]{0,3}",start or "") or not re.fullmatch(r"[1-9][0-9]{0,3}",last)
                    or not re.fullmatch(r"-?[0-9]{1,5}",offset or "") or int(start)>int(last)):
                raise ReleaseNotReady("RELEASE_MAPPING_UNSUPPORTED")
            rules.append((1,int(start),int(last),target_season,int(offset)))
    default_season,default_offset=node.get("defaulttvdbseason"),node.get("episodeoffset") or "0"
    default=None
    if re.fullmatch(r"[0-9]{1,3}",default_season or "") and re.fullmatch(r"-?[0-9]{1,5}",default_offset or ""):
        default=(int(default_season),int(default_offset))
    resolved={}
    for number in catalog:
        applicable=[rule for rule in rules if rule[1]<=number<=rule[2]]
        if applicable:
            priority=max(rule[0] for rule in applicable)
            targets={(rule[3],number+rule[4]) for rule in applicable if rule[0]==priority}
            if len(targets)!=1: raise ReleaseConflict()
            target=targets.pop()
        elif default is not None:
            target=(default[0],number+default[1])
        else: continue
        if target[1]>0: resolved[number]=target
    return resolved
