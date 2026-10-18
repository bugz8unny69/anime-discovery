"""Read-only release-to-catalog candidate gate. Never grants production approval.

A catalog comparison is not a file-content attestation, nor independent
release-numbering evidence. No network, database, or torrent mutations.
"""
from dataclasses import dataclass
from pathlib import PurePosixPath
import re
from release_identity import parse_release_title

class ReleaseBlocked(ValueError):
    pass

@dataclass(frozen=True)
class Candidate:
    status: str
    season: int
    episode: int
    title: str
    reasons: tuple
    canonical_mapping_authorized: bool = False
    release_mapping_verified: bool = False
    keep_or_reject_authorized: bool = False

def _safe_name(name):
    if not isinstance(name, str) or not name or len(name) > 512 or '\x00' in name or '/' in name or '\\' in name:
        raise ReleaseBlocked('INVALID_RELEASE_NAME')
    return name

def _episode_from_name(name):
    result = parse_release_title(_safe_name(name))
    if not result['accepted']:
        raise ReleaseBlocked('UNSAFE_EPISODE_LABEL:' + str(result['reason']))
    return result['episode']

def assess_release(catalog, *, release_name, file_names, expected_series_label):
    """Validate single-file candidate against a six-episode reference catalog.

    Names are untrusted hints. This never verifies media content, provider
    authenticity, actual torrent membership, or canonical numbering provenance.
    """
    if not isinstance(catalog, dict) or catalog.get('status') != 'CANDIDATE_ONLY' or catalog.get('canonical_mapping_authorized') is not False:
        raise ReleaseBlocked('CATALOG_NOT_CANDIDATE')
    prefix = catalog.get('prefix')
    if not isinstance(prefix, list) or not 1 <= len(prefix) <= 6:
        raise ReleaseBlocked('INVALID_PREFIX')
    for i, row in enumerate(prefix, 1):
        if (not isinstance(row, dict) or type(row.get('season')) is not int or row['season'] != 1
                or type(row.get('episode')) is not int or row['episode'] != i
                or not isinstance(row.get('sonarr_title'), str) or not row['sonarr_title'].strip()
                or not isinstance(row.get('tvmaze_title'), str) or not row['tvmaze_title'].strip()
                or row['sonarr_title'].casefold().strip() != row['tvmaze_title'].casefold().strip()):
            raise ReleaseBlocked('CATALOG_PREFIX_CONFLICT')
    label = _safe_name(expected_series_label)
    if len(label) < 3 or not re.search(re.escape(label), _safe_name(release_name), re.IGNORECASE):
        raise ReleaseBlocked('SERIES_LABEL_MISSING')
    episode = _episode_from_name(release_name)
    if episode > len(prefix):
        raise ReleaseBlocked('EPISODE_OUTSIDE_CATALOG')
    if not isinstance(file_names, (tuple, list)) or len(file_names) != 1:
        raise ReleaseBlocked('EXACTLY_ONE_FILE_REQUIRED')
    file_name = _safe_name(file_names[0])
    if PurePosixPath(file_name).suffix.lower() not in ('.mkv', '.mp4'):
        raise ReleaseBlocked('UNSUPPORTED_FILE_EXTENSION')
    if not re.search(re.escape(label), file_name, re.IGNORECASE):
        raise ReleaseBlocked('FILE_SERIES_LABEL_MISSING')
    if _episode_from_name(str(PurePosixPath(file_name).with_suffix(''))) != episode:
        raise ReleaseBlocked('RELEASE_FILE_EPISODE_MISMATCH')
    return Candidate('CANDIDATE_ONLY', 1, episode, prefix[episode - 1]['sonarr_title'],
                     ('CATALOG_AGREEMENT_NOT_RELEASE_PROVENANCE',
                      'FILE_CONTENT_NOT_VERIFIED', 'INDEPENDENT_NUMBERING_EVIDENCE_REQUIRED'))
