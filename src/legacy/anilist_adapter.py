"""Read-only AniList ID lookup. This module NEVER authorizes episode mappings."""
import json
import urllib.error
import urllib.request

ENDPOINT = 'https://graphql.anilist.co'
QUERY = '''query ($id: Int) {
  Media(id: $id, type: ANIME) {
    id idMal title { romaji english native }
    format episodes season seasonYear isAdult
  }
}'''

class MetadataLookupError(Exception):
    pass


def validate_media(media, expected_id):
    """Validate shape/identity; return a normalized identity record, not approval."""
    if not isinstance(media, dict) or type(media.get('id')) is not int or media['id'] != expected_id:
        raise MetadataLookupError('ID_MISMATCH')
    titles = media.get('title')
    if not isinstance(titles, dict) or not any(isinstance(titles.get(k), str) and titles[k].strip() for k in ('romaji', 'english', 'native')):
        raise MetadataLookupError('MISSING_TITLE')
    episodes = media.get('episodes')
    if type(episodes) is not int or episodes < 1:
        raise MetadataLookupError('MISSING_EPISODE_COUNT')
    if media.get('isAdult') is not False:
        raise MetadataLookupError('ADULT_STATUS_UNVERIFIED_OR_ADULT')
    if media.get('format') not in ('TV', 'TV_SHORT'):
        raise MetadataLookupError('UNSUPPORTED_FORMAT')
    return {
        'anilist_id': expected_id,
        'mal_id': media.get('idMal') if type(media.get('idMal')) is int else None,
        'titles': {k: titles.get(k) for k in ('romaji', 'english', 'native')},
        'episodes': episodes,
        'season': media.get('season'),
        'season_year': media.get('seasonYear'),
        'format': media['format'],
        'identity_only': True,
        'canonical_mapping_authorized': False,
    }


def lookup_by_id(anilist_id, transport=None):
    """Explicit numeric ID only. Optional injected transport enables offline tests."""
    if type(anilist_id) is not int or anilist_id < 1:
        raise MetadataLookupError('INVALID_ANILIST_ID')
    payload = json.dumps({'query': QUERY, 'variables': {'id': anilist_id}}).encode('utf-8')
    if transport is None:
        def transport(request):
            with urllib.request.urlopen(request, timeout=15) as response:
                return response.read()
    request = urllib.request.Request(ENDPOINT, data=payload, method='POST', headers={
        'Content-Type': 'application/json', 'Accept': 'application/json',
        'User-Agent': 'AnimeDiscoveryLab/0.1',
    })
    try:
        raw = transport(request)
        response = json.loads(raw)
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, TypeError) as exc:
        raise MetadataLookupError('NETWORK_OR_RESPONSE_ERROR') from exc
    if not isinstance(response, dict) or response.get('errors') or not isinstance(response.get('data'), dict):
        raise MetadataLookupError('GRAPHQL_ERROR')
    return validate_media(response['data'].get('Media'), anilist_id)
