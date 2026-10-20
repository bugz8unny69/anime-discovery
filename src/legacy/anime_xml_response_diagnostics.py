"""Bounded, credential-redacted diagnostics for upstream XML payloads.

Log only source labels, response metadata, an abbreviated content fingerprint,
and a tightly constrained prefix; never log request URLs, auth headers,
registered client IDs, API tokens, or the complete response body.
"""
import hashlib
import logging
import re
import xml.etree.ElementTree as ET

LOG=logging.getLogger(__name__)

ENDPOINTS={
    "ANIDB_TITLES":"https://anidb.net/api/anime-titles.xml.gz",
    "ANIDB_TITLES_CACHE":"https://anidb.net/api/anime-titles.xml.gz",
    "ANIME_LISTS":"https://raw.githubusercontent.com/Anime-Lists/anime-lists/master/anime-list.xml",
    "ANIME_LISTS_MAPPING":"https://raw.githubusercontent.com/Anime-Lists/anime-lists/master/anime-list.xml",
    "ANIDB_EPISODE_HTTP":"http://api.anidb.net:9001/httpapi",
}

class InvalidXMLResponse(ValueError):
    """Remote XML metadata unavailable/invalid; identity should retry."""
    def __init__(self,source,kind="INVALID_XML"):
        self.source=source
        self.kind=kind
        super().__init__(source+" "+kind)


def _payload_preview(raw):
    """Only ASCII markup or plain-text error prefixes; redact private values."""
    if not isinstance(raw,bytes):
        return "non_bytes"
    sample=raw[:160].decode("utf-8","replace")
    # Never log provider-returned bearer tokens or other credential-like fields.
    sample=re.sub(r"(?i)(?:api[_-]?key|client|clientver|token|password|pass|"
                  r"authorization|cookie|secret)\s*[:=]\s*['\"]?[^\s&<>\"']+",
                  "[redacted]",sample)
    sample=re.sub(r"(?i)https?://[^\s<>\"']+","[url]",sample)
    sample="".join(c if 32<=ord(c)<=126 else " " for c in sample)
    # Whitelist readable characters and limit attack-controlled log content.
    return re.sub(r"[^a-zA-Z0-9 <>/!?_.:;=\-()\[\]#]","?",sample)[:96]


def response_metadata(source,payload,*,status=None,content_type=None):
    if source not in ENDPOINTS:
        raise ValueError("Unknown XML metadata source")
    raw=payload if isinstance(payload,bytes) else b""
    return {
        "source":source,
        "endpoint":ENDPOINTS[source],
        "http_status":status if type(status) is int else "unknown",
        "content_type":str(content_type or "unknown").split(";",1)[0][:48],
        "bytes":len(raw),
        "sha256_12":hashlib.sha256(raw).hexdigest()[:12],
        "prefix":_payload_preview(raw),
    }


def log_bad_xml(source,payload,*,status=None,content_type=None,reason="INVALID_XML",
                content_encoding=None,encoded_bytes=None):
    info=response_metadata(source,payload,status=status,content_type=content_type)
    # Never log arbitrary server-returned encoding header values.
    coding=str(content_encoding or "unknown").strip().lower()
    if coding not in ("gzip","x-gzip","deflate","identity"):
        coding="unknown"
    original_size=(encoded_bytes if type(encoded_bytes) is int and
                   encoded_bytes>=0 else info["bytes"])
    # The endpoint here is a fixed public address, never a request/query URL.
    LOG.warning("upstream_xml_problem source=%s endpoint=%s http_status=%s "
                "content_type=%s content_encoding=%s encoded_bytes=%s "
                "bytes=%s sha256_12=%s preview=%r reason=%s",
                info["source"],info["endpoint"],info["http_status"],
                info["content_type"],coding,original_size,info["bytes"],
                info["sha256_12"],info["prefix"],reason)
    return info
