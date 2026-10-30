"""Audio requirement setting and the release-title audio hint.

The title hint only orders work (rank first, or search instead of downloading
an untagged webhook release). The ffprobe check stays the only proof.
"""
import re

OFF = 'off'
JAPANESE = 'japanese'
JAPANESE_ENGLISH = 'japanese_english'
MODES = (OFF, JAPANESE, JAPANESE_ENGLISH)

_REQUIRED = {OFF: frozenset(), JAPANESE: frozenset({'jpn'}),
             JAPANESE_ENGLISH: frozenset({'jpn', 'eng'})}

# Groups spell this many ways. "Multi-Subs" is subtitles and does not count.
_SEP = r'[ ._+&/,-]*'
_JA = r'(?:ja|jp|jpn|jap|japanese)'
_EN = r'(?:en|eng|english)'
_TAG = re.compile(
    r'(?<![a-z0-9])(?:'
    r'dual' + _SEP + r'(?:audio|aud)?'
    r'|multi' + _SEP + r'(?:audio|aud)'
    r'|multi(?!' + _SEP + r'(?:sub|subs|subtitles?)\b)'
    r'|' + _EN + _SEP + r'dub(?:bed|s)?'
    r'|dub(?:bed)?'
    r'|' + _JA + _SEP + _EN + r'|' + _EN + _SEP + _JA +
    r')(?![a-z0-9])', re.I)


def required_languages(mode):
    """Audio languages ffprobe must find; empty means no language check."""
    try:
        return _REQUIRED[mode]
    except (KeyError, TypeError):
        raise ValueError('unknown audio check') from None


def wants_english(mode):
    return 'eng' in required_languages(mode)


def audio_tagged(title):
    """True when the release title advertises dual/multi audio or an English dub."""
    return type(title) is str and _TAG.search(title) is not None
