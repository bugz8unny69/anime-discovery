"""Read-only shared settings resolver. Explicit saved settings > legacy env > default.

Call get() at point of use for hot-reload; never cache secrets in logs.
"""
import json
import os
from pathlib import Path
from anime_discovery import SCHEMA, ENV_MAP, validate


def get(key, *, default=None):
    if key not in SCHEMA:
        raise KeyError(key)
    path = Path(os.environ.get('ANIME_CONFIG_DIR', '/etc/anime-discovery')) / ('secrets.json' if SCHEMA[key][0] == 'secret' else 'config.json')
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        data = {}
    if not isinstance(data, dict):
        raise ValueError('Invalid configuration object')
    if key in data:
        return validate(key, data[key])
    env = ENV_MAP.get(key)
    if env and env in os.environ:
        return validate(key, os.environ[env])
    return SCHEMA[key][1] if default is None else default


def data_path(filename):
    """Resolve a single state filename inside the configured data directory."""
    if not isinstance(filename, str) or filename in ('', '.', '..') or Path(filename).name != filename or '/' in filename or '\\' in filename:
        raise ValueError('Expected a single state filename')
    root = Path(get('discovery.data_dir')).resolve()
    return root / filename
