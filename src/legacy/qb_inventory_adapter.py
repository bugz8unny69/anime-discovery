"""Read-only qBittorrent inventory and fail-closed cancellation preflight.

No login, POST, DELETE, or torrent modification. Caller supplies an already
established qBittorrent SID cookie and trusted attempt->hash bindings from DB.
"""
from dataclasses import dataclass
import ipaddress
import json
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

HASH_RE = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')
ACTIVE = frozenset({'downloading', 'stalledDL', 'metaDL', 'forcedDL', 'queuedDL', 'checkingDL',
                    'uploading', 'stalledUP', 'forcedUP', 'queuedUP', 'pausedDL', 'pausedUP',
                    'stoppedDL', 'stoppedUP', 'checkingUP', 'checkingResumeData', 'moving',
                    'allocating', 'error', 'missingFiles', 'unknown'})

class InventoryError(ValueError):
    pass

@dataclass(frozen=True)
class InventoryItem:
    torrent_hash: str
    state: str
    name: str

@dataclass(frozen=True)
class CancellationPreflight:
    attempt_id: int
    torrent_hash: str
    outcome: str  # WOULD_REMOVE_TORRENT_ONLY, ALREADY_ABSENT, BLOCKED
    reason: str
    dry_run: bool = True


def validate_base_url(base_url):
    if not isinstance(base_url, str):
        raise InventoryError('Invalid URL')
    p = urlsplit(base_url)
    if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.query or p.fragment or p.path not in ('', '/'):
        raise InventoryError('Invalid qBittorrent base URL')
    try:
        port = p.port
    except ValueError as exc:
        raise InventoryError('Invalid port') from exc
    if port is not None and port <= 0:
        raise InventoryError('Invalid port')
    if p.scheme == 'http':
        try:
            if not ipaddress.ip_address(p.hostname).is_loopback:
                raise InventoryError('HTTP allowed only on loopback')
        except ValueError as exc:
            if isinstance(exc, InventoryError):
                raise
            raise InventoryError('HTTP requires literal loopback IP') from exc
    return base_url.rstrip('/')


def parse_inventory(payload):
    if isinstance(payload, bytes):
        if len(payload) > 4_000_000:
            raise InventoryError('Inventory response too large')
        try:
            payload = json.loads(payload.decode('utf-8'))
        except (UnicodeError, ValueError) as exc:
            raise InventoryError('Invalid JSON') from exc
    if not isinstance(payload, list) or len(payload) > 10000:
        raise InventoryError('Expected bounded torrent list')
    seen = set()
    result = []
    for item in payload:
        if not isinstance(item, dict):
            raise InventoryError('Invalid torrent record')
        h, state, name = item.get('hash'), item.get('state'), item.get('name')
        if not isinstance(h, str) or not HASH_RE.fullmatch(h):
            raise InventoryError('Invalid torrent hash')
        h = h.lower()
        if h in seen:
            raise InventoryError('Duplicate torrent hash')
        seen.add(h)
        if not isinstance(state, str) or state not in ACTIVE:
            raise InventoryError('Unknown torrent state')
        if not isinstance(name, str) or len(name) > 2048:
            raise InventoryError('Invalid torrent name')
        result.append(InventoryItem(h, state, name))
    return tuple(result)


def fetch_inventory(base_url, sid, *, transport=None):
    base = validate_base_url(base_url)
    if not isinstance(sid, str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,256}', sid):
        raise InventoryError('Invalid SID cookie')
    url = base + '/api/v2/torrents/info'
    request = Request(url, headers={'Cookie': 'SID=' + sid, 'Accept': 'application/json', 'User-Agent': 'AnimeDiscoveryReadOnly/0.1'}, method='GET')
    try:
        if transport is None:
            # Redirects can forward the SID to another origin: disable them.
            from urllib.request import build_opener, HTTPRedirectHandler
            class NoRedirect(HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None
            opener = build_opener(NoRedirect())
            response = opener.open(request, timeout=10)
        else:
            response = transport(request)
        with response:
            if response.getcode() != 200:
                raise InventoryError('Unexpected HTTP status')
            data = response.read(4_000_001)
        return parse_inventory(data)
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise InventoryError('qBittorrent inventory request failed') from exc


def preflight(attempt_id, bound_hash, inventory, *, current_attempt_id=None):
    """Bound hash MUST come from trusted attempt storage, not qB inventory.

    current_attempt_id is the latest active attempt for this episode, as read
    from trusted storage. A stale attempt is blocked, even if its hash exists.
    """
    if type(attempt_id) is not int or attempt_id <= 0:
        raise InventoryError('Invalid attempt ID')
    if not isinstance(bound_hash, str) or not HASH_RE.fullmatch(bound_hash):
        raise InventoryError('Invalid bound hash')
    if current_attempt_id is not None and (type(current_attempt_id) is not int or current_attempt_id <= 0):
        raise InventoryError('Invalid current attempt ID')
    if not isinstance(inventory, tuple) or any(not isinstance(i, InventoryItem) for i in inventory):
        raise InventoryError('Unvalidated inventory')
    h = bound_hash.lower()
    if current_attempt_id is not None and current_attempt_id != attempt_id:
        return CancellationPreflight(attempt_id, h, 'BLOCKED', 'Stale attempt')
    matching = [item for item in inventory if item.torrent_hash == h]
    if len(matching) > 1:
        raise InventoryError('Duplicate torrent hash')
    if not matching:
        return CancellationPreflight(attempt_id, h, 'ALREADY_ABSENT', 'Hash absent from full inventory')
    return CancellationPreflight(attempt_id, h, 'WOULD_REMOVE_TORRENT_ONLY', 'Dry-run; do not delete files')
