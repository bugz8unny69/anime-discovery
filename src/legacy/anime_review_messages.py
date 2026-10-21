"""Concise operator descriptions for durable internal review reason codes.

Do not persist presentation text: persisted scheduler codes remain stable
across upgrades. Unknown errors become an actionable generic message.
"""
from types import MappingProxyType

REVIEW_DESCRIPTIONS = MappingProxyType({
    "TRIAL_TOTAL_EXCEEDED": "Torrent exceeds the configured download size limit.",
    "EPISODE_SIZE_EXCEEDED": "Episode exceeds the configured download size limit.",
    "CONFLICTING_EPISODE_SIZE": "Episode size differs from an earlier download.",
    "CONFLICTING_EPISODE_RESERVATION": "Another torrent already reserves this episode.",
    "QBITTORRENT_SAVE_PATH_OUTSIDE_DOWNLOAD_ROOT": "Torrent is outside the configured download folder.",
    "BATCH_MANIFEST_INTAKE_REJECTED": "The torrent file list could not be verified.",
    "JAPANESE_ENGLISH_REQUIRED": "Required Japanese and English audio tracks were not confirmed.",
    "BATCH_EPISODES_UNMAPPABLE": "Torrent episodes could not be matched reliably.",
    "BATCH_PLAN_CHANGED_AFTER_RESERVATION": "The torrent file list changed; review required.",
    "PROVIDER_CACHE_CHANGED": "Identity information changed; verify the series again.",
})

def describe_review(code):
    """Return bounded user-facing text; never echo untrusted exception strings."""
    if not code:
        return "Review required. See service logs for details."
    if str(code).startswith("LOOKUP_"):
        return "An internal series identification check failed."
    return REVIEW_DESCRIPTIONS.get(str(code),
        "Processing needs attention. See service logs for details.")
