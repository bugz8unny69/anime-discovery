"""Offline tests. No network, DB, downloads, or controller changes."""
import copy
import json
from anilist_adapter import lookup_by_id, MetadataLookupError

MEDIA = {
    'id': 11061, 'idMal': 11061,
    'title': {'romaji': 'HUNTER×HUNTER (2011)', 'english': 'Hunter x Hunter (2011)', 'native': 'HUNTER×HUNTER (2011)'},
    'format': 'TV', 'episodes': 148, 'season': 'FALL', 'seasonYear': 2011, 'isAdult': False,
}

checks = 0

def check(name, media=None, error=None, response=None):
    global checks
    if response is None:
        response = {'data': {'Media': copy.deepcopy(MEDIA if media is None else media)}}
    def transport(request):
        assert request.get_method() == 'POST'
        assert json.loads(request.data)['variables']['id'] == 11061
        return json.dumps(response).encode()
    try:
        result = lookup_by_id(11061, transport=transport)
        assert error is None, f'Expected {error}, accepted {result}'
        assert result['identity_only'] and result['canonical_mapping_authorized'] is False
    except MetadataLookupError as exc:
        assert str(exc) == error, (name, str(exc), error)
    checks += 1
    print('PASS', name)

check('valid identity, never authorizes mapping')
for name, change, expected in [
    ('mismatched ID', {'id': 9}, 'ID_MISMATCH'),
    ('missing title', {'title': {}}, 'MISSING_TITLE'),
    ('unknown episode count', {'episodes': None}, 'MISSING_EPISODE_COUNT'),
    ('zero episodes', {'episodes': 0}, 'MISSING_EPISODE_COUNT'),
    ('adult series', {'isAdult': True}, 'ADULT_STATUS_UNVERIFIED_OR_ADULT'),
    ('unknown adult flag', {'isAdult': None}, 'ADULT_STATUS_UNVERIFIED_OR_ADULT'),
    ('movie', {'format': 'MOVIE'}, 'UNSUPPORTED_FORMAT'),
    ('OVA', {'format': 'OVA'}, 'UNSUPPORTED_FORMAT'),
]:
    item = {**MEDIA, **change}
    check(name, item, expected)
check('GraphQL errors', error='GRAPHQL_ERROR', response={'errors': [{'message': 'rate limit'}]})
check('missing data', error='GRAPHQL_ERROR', response={})
check('missing media', error='ID_MISMATCH', response={'data': {'Media': None}})
for value in ('11061', True, 0, -1, None):
    try:
        lookup_by_id(value, transport=lambda _: b'{}')
    except MetadataLookupError as exc:
        assert str(exc) == 'INVALID_ANILIST_ID'
    else:
        raise AssertionError('Accepted invalid ID')
    checks += 1
    print('PASS invalid ID', repr(value))
try:
    lookup_by_id(11061, transport=lambda _: b'not-json')
except MetadataLookupError as exc:
    assert str(exc) == 'NETWORK_OR_RESPONSE_ERROR'
else:
    raise AssertionError('Accepted malformed JSON')
checks += 1
print('PASS malformed response')
print(f'\nAll {checks} AniList adapter tests passed.')
