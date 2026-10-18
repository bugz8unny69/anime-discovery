"""Automatic episode approval policy: only ambiguous evidence needs review.

Pure decision logic. The caller must persist approval atomically with canonical
series resolution and recheck rejection before any torrent or file action.
"""
from __future__ import annotations

def decide_episode(shadow: dict, verification: dict, *, series_blocked: bool = False) -> dict:
    """Choose AUTO_APPROVED, NEEDS_REVIEW, or BLOCKED.

    Score is not a probability. All independent ordering checks are mandatory.
    """
    if series_blocked:
        return {"decision": "BLOCKED", "reason": "SERIES_REJECTED", "eligible_for_acquisition": False}
    policy = shadow.get("policy")
    if not isinstance(policy, dict) or policy.get("enabled") is not True:
        return {"decision": "NEEDS_REVIEW", "reason": "POLICY_UNAVAILABLE", "eligible_for_acquisition": False}
    threshold = policy.get("auto_approve_threshold")
    score = shadow.get("score_points")
    if type(threshold) is not int or not 0 <= threshold <= 100 or type(score) is not int:
        return {"decision": "NEEDS_REVIEW", "reason": "INVALID_CONFIDENCE", "eligible_for_acquisition": False}
    if shadow.get("decision") != "SHADOW_HIGH_CONFIDENCE" or score < threshold or shadow.get("blockers"):
        return {"decision": "NEEDS_REVIEW", "reason": "IDENTITY_CONFIDENCE_INSUFFICIENT", "eligible_for_acquisition": False}
    mapping = verification.get("proposed_mapping")
    valid_mapping = (
        isinstance(mapping, dict)
        and str(mapping.get("tvdb_id", "")).isdigit()
        and int(mapping["tvdb_id"]) > 0
        and type(mapping.get("tvdb_season")) is int
        and mapping["tvdb_season"] >= 1
        and type(mapping.get("tvdb_episode")) is int
        and mapping["tvdb_episode"] >= 1
    )
    if (
        verification.get("decision") != "AUTO_VERIFIED_CANDIDATE"
        or verification.get("episode_identity_verified") is not True
        or verification.get("blockers")
        or not valid_mapping
    ):
        return {"decision": "NEEDS_REVIEW", "reason": "EPISODE_ORDERING_NOT_VERIFIED", "eligible_for_acquisition": False}
    return {
        "decision": "AUTO_APPROVED",
        "reason": "HIGH_CONFIDENCE_AND_VERIFIED_EPISODE_ORDERING",
        "eligible_for_acquisition": True,
        "mapping": dict(mapping),
        "confidence_score": score,
    }
