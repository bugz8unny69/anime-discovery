"""Post-Sonarr Shoko handoff: exact-path reconciliation, safe by default.

Only Anime Discovery's verified Sonarr destinations are eligible. A trusted
AniDB *episode* ID is mandatory; a TVDB series or AniDB anime ID is insufficient.
No automatic Shoko mutation is issued by this module.
"""
from pathlib import Path
from anime_shoko_v3 import _get, get_file, resolve_episode

def inspect_imported_episode(base_url, api_key, *, destination, sonarr_root,
                             anidb_episode_id, verified_episode_identity,
                             opener=None):
    """Return a deterministic plan; only GET requests. No guessing or linking."""
    opts={} if opener is None else {"opener":opener}
    path=Path(destination).resolve(strict=True)
    root=Path(sonarr_root).resolve(strict=True)
    if not path.is_file() or path==root or not path.is_relative_to(root):
        raise ValueError("Destination not inside permanent Sonarr library")
    if type(anidb_episode_id) is not int or anidb_episode_id<=0 or verified_episode_identity is not True:
        return {"status":"NEEDS_EPISODE_IDENTITY","writes_enabled":False}
    # Shoko path search is suffix-based. A result must be independently
    # verified with its absolute location, not inferred from a basename.
    candidates=_get(base_url,api_key,"File/PathEndsWith",
                    {"path":path.name,"limit":100},**opts)
    if not isinstance(candidates,list):
        raise RuntimeError("Invalid Shoko search response")
    verified=[]
    for candidate in candidates:
        if not isinstance(candidate,dict) or type(candidate.get("ID")) is not int:
            continue
        file_id=candidate["ID"]
        locations=_get(base_url,api_key,"File/"+str(file_id)+"/Location",
                       {"includeAbsolutePaths":"true"},**opts)
        if not isinstance(locations,list):
            raise RuntimeError("Invalid Shoko location response")
        if any(isinstance(loc,dict) and loc.get("FileID")==file_id
               and loc.get("AbsolutePath")==str(path)
               and loc.get("IsAccessible") is True for loc in locations):
            verified.append(file_id)
    if not verified:
        return {"status":"AWAITING_SHOKO_SCAN","writes_enabled":False}
    if len(set(verified))!=1:
        return {"status":"AMBIGUOUS_SHOKO_FILE","writes_enabled":False}
    file_id=verified[0]
    record=get_file(base_url,api_key,file_id,**opts)
    # Null is an unknown link state, NOT evidence that no links exist.
    if record.get("SeriesIDs") is None:
        return {"status":"UNRECOGNIZED_NEEDS_REVIEW","file_id":file_id,
                "writes_enabled":False}
    if record.get("SeriesIDs")!=[]:
        return {"status":"SHOKO_ALREADY_LINKED","file_id":file_id,
                "writes_enabled":False}
    ep=resolve_episode(base_url,api_key,anidb_episode_id,**opts)
    return {"status":"LINK_PLAN_READY","file_id":file_id,
            "anidb_episode_id":anidb_episode_id,
            "shoko_episode_id":ep["shoko_episode_id"],
            "method":"POST","path":"/api/v3/File/"+str(file_id)+"/Link",
            "body":{"EpisodeIDs":[ep["shoko_episode_id"]]},
            "writes_enabled":False}
