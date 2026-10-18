"""Validate a read-only qBittorrent torrent/file snapshot.

The caller supplies the authenticated qBittorrent API adapter. No submission,
torrent deletion, or media file changes occur.
"""
import json
from urllib.parse import urlencode

def completed_torrent_snapshot(qb, infohash):
    if not isinstance(infohash,str) or len(infohash) not in (40,64):
        raise ValueError("Invalid torrent hash")
    infohash=infohash.lower()
    if any(char not in "0123456789abcdef" for char in infohash):
        raise ValueError("Invalid torrent hash")
    raw=qb._request("torrents/info?"+urlencode({"hashes":infohash}))
    torrents=json.loads(raw)
    if not isinstance(torrents,list):
        raise ValueError("Invalid torrent response")
    matching=[torrent for torrent in torrents
              if isinstance(torrent,dict) and
              str(torrent.get("hash","")).lower()==infohash]
    if len(matching)!=1:
        raise ValueError("Expected exactly one matching torrent")
    files=json.loads(qb._request("torrents/files?"+urlencode({"hash":infohash})))
    if not isinstance(files,list):
        raise ValueError("Invalid file manifest")
    result=dict(matching[0])
    result["files"]=files
    return result
