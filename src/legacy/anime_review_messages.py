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
    "NO_TVDB_SEARCH_RESULTS": "TVDB returned no matching series. Check the release title or use Resolve with verified TVDB and AniDB IDs.",
    "ALL_TVDB_TITLES_BELOW_THRESHOLD": "TVDB returned candidates, but none met the title-match threshold. Review Matching details or use Resolve with verified IDs.",
    "AMBIGUOUS_TVDB_CANDIDATES": "Several TVDB series could match. Review Matching details to identify the correct series.",
    "TVDB_DISABLED_OR_KEY_MISSING": "TVDB lookup is disabled or its API key is missing. Check integration settings.",
    "AMBIGUOUS_ANIDB_TITLES": "Multiple AniDB titles could match. Review Matching details before resolving the identity.",
    "ANIDB_PUBLIC_SOURCE_DISABLED": "Automatic AniDB title lookup is disabled. Check settings or resolve the title manually.",
})

def describe_review(code):
    """Return bounded user-facing text; never echo untrusted exception strings."""
    if not code:
        return "Identity review is required. Open Matching details for the recorded evidence."
    if str(code).startswith("LOOKUP_"):
        return "An identity lookup encountered a technical error, not necessarily a missing TVDB match. Open Matching details for available evidence."
    return REVIEW_DESCRIPTIONS.get(str(code),
        "Automatic identification needs review. Open Matching details, then use Resolve if you can verify the IDs.")
