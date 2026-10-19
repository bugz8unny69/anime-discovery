"""qBittorrent submission boundary, with injected transport for offline tests.

The caller must supply an approved, rechecked dispatch and a normalized
infohash. Never modifies qBittorrent download limits or torrent priority.
"""
import hashlib
from urllib.parse import urlsplit, parse_qs
from anime_external_actions import reserve, transition
from anime_action_reconcile import reconcile

def submit_once(db, infohash, magnet_uri, qb):
    """Fail closed after uncertain submission; reconcile rather than retry.

    qb exposes contains_hash(infohash) and add_magnet(magnet_uri).
    """
    if not isinstance(infohash,str) or len(infohash) not in (40,64) or any(c not in "0123456789abcdef" for c in infohash.lower()):
        raise ValueError("Invalid torrent infohash")
    infohash=infohash.lower()
    if not isinstance(magnet_uri,str) or not magnet_uri.startswith("magnet:?"):
        raise ValueError("Expected magnet URI")
    xt=parse_qs(urlsplit(magnet_uri).query).get("xt",[])
    if not any(value.lower()=="urn:btih:"+infohash for value in xt):
        raise ValueError("Magnet identity does not match verified infohash")
    fingerprint=hashlib.sha256(magnet_uri.encode()).hexdigest()
    action="qbittorrent_submit"
    token=reserve(db,action,infohash,fingerprint)
    if token is None:
        # Recover a crash after reservation without ever resubmitting blindly.
        row=db.execute('SELECT state,token FROM external_actions WHERE action_type=? AND action_key=?',(action,infohash)).fetchone()
        if row and row[0]=='RESERVED':
            transition(db,action,infohash,row[1],'RESERVED','UNCERTAIN')
        return reconcile(db,action,infohash,fingerprint,
                         lambda _type,key: key if qb.contains_hash(key) else None)
    transition(db,action,infohash,token,"RESERVED","UNCERTAIN")
    # Recheck before sending, including a torrent already added manually.
    if not qb.contains_hash(infohash):
        qb.add_magnet(magnet_uri)
    # A successful API response alone is not confirmation; read back.
    return reconcile(db,action,infohash,fingerprint,
                     lambda _type,key: key if qb.contains_hash(key) else None)
