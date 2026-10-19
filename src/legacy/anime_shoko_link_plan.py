"""Pure, fail-closed Shoko episode-link decision logic.

Shoko VFS is authoritative. This module never performs HTTP requests or
writes. The caller must supply separately verified file/episode observations.
"""
def plan_episode_link(*, contract, file_observation, anidb_episode_id,
                      identity_verified, episode_order_verified):
    blocked={"action":"NO_WRITE","writes_enabled":False}
    if not isinstance(contract,dict) or contract.get("validated") is not True:
        return {**blocked,"reason":"Shoko API contract not validated"}
    if not isinstance(anidb_episode_id,int) or isinstance(anidb_episode_id,bool) or anidb_episode_id<=0:
        return {**blocked,"reason":"Exact AniDB episode ID required"}
    if identity_verified is not True or episode_order_verified is not True:
        return {**blocked,"reason":"Series identity and episode ordering must be verified"}
    if not isinstance(file_observation,dict):
        return {**blocked,"reason":"Shoko file observation required"}
    if file_observation.get("recognized") is True:
        return {**blocked,"reason":"Shoko-recognized files are authoritative"}
    if file_observation.get("recognized") is not False:
        return {**blocked,"reason":"Unknown Shoko recognition state"}
    if file_observation.get("existing_episode_ids") != []:
        return {**blocked,"reason":"Existing or unknown episode links require review"}
    if file_observation.get("file_id") is None:
        return {**blocked,"reason":"Verified Shoko file ID required"}
    if type(file_observation["file_id"]) is not int or file_observation["file_id"]<=0:
        return {**blocked,"reason":"Invalid Shoko file ID"}
    return {"action":"ELIGIBLE_FOR_SEPARATE_REVIEW","writes_enabled":False,
            "file_id":file_observation["file_id"],
            "anidb_episode_id":anidb_episode_id,
            "reason":"All offline preconditions met; no write operation authorized"}
