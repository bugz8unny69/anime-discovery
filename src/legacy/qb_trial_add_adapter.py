"""qBittorrent magnet add adapter. Disabled by default; no production wiring.

The coordinator's pre/post inventory and journal are required separately.
This module does not establish exclusive ownership or authorize cancellation.
"""
import re
import urllib.parse
from anime_service_adapters import QBittorrentReadOnly, AdapterError

_HEX = re.compile(r'^[0-9a-fA-F]{40}$')
_CATEGORY = 'anime-trial'
_SAVE = '/mnt/media/Torrents/anime-trial'

class TrialAddDisabled(RuntimeError):
    pass

def validate_magnet(magnet, expected_hash):
    if not isinstance(expected_hash, str) or not _HEX.fullmatch(expected_hash):
        raise ValueError('invalid expected hash')
    if not isinstance(magnet, str) or len(magnet) > 8192:
        raise ValueError('invalid magnet')
    u = urllib.parse.urlsplit(magnet)
    if u.scheme != 'magnet' or u.netloc or u.fragment:
        raise ValueError('invalid magnet scheme')
    params = urllib.parse.parse_qs(u.query, keep_blank_values=True)
    xt = params.get('xt', [])
    if len(xt) != 1 or xt[0].lower() != 'urn:btih:' + expected_hash.lower():
        raise ValueError('magnet infohash mismatch or ambiguity')
    if any(k.lower() in ('xs', 'as', 'ws', 'mt') for k in params):
        raise ValueError('external source magnet parameters not permitted')
    return magnet

class QBTrialAdd(QBittorrentReadOnly):
    """Only add a vetted magnet; explicit opt-in and prior login required.

    This is an adapter primitive, not a production-ready add workflow.
    """
    def add_trial_magnet(self, magnet, expected_hash, *, allow_external_write=False):
        if not allow_external_write:
            raise TrialAddDisabled('external qB writes disabled')
        if not self._authenticated:
            raise AdapterError('qB login required')
        validate_magnet(magnet, expected_hash)
        # qB 4.5.2 Web API: POST /api/v2/torrents/add.
        # Category is a label, not proof of ownership. Never auto-create it.
        result = self._request('/api/v2/torrents/add', form={
            'urls': magnet,
            'category': _CATEGORY,
            'savepath': _SAVE,
            'paused': 'true',
            'autoTMM': 'false',
        })
        if result.strip() != 'Ok.':
            raise AdapterError('qB add response uncertain; do not retry automatically')
        return True
