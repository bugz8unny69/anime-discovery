#!/usr/bin/env python3
"""Idempotently patch installed config manager and controller. Back up before running."""
from pathlib import Path

config = Path('anime_discovery.py')
api = Path('api.py')
for p in (config, api):
    if not p.is_file():
        raise SystemExit(f'Missing {p}; run from /opt/anime-discovery')

s = config.read_text()
if "'controller.api_token': ('secret'" not in s:
    needle = "SCHEMA = {\n"
    assert s.count(needle) == 1, 'Unexpected configuration schema'
    s = s.replace(needle, needle + " 'controller.api_token': ('secret', None, 'next request'),\n", 1)
    config.write_text(s)

s = api.read_text()
old = '    token = os.environ.get("ANIME_DISCOVERY_TOKEN")'
if old in s:
    new = '''    # Shared protected config, with legacy environment fallback.
    try:
        from anime_config_runtime import get as config_get
        token = config_get("controller.api_token") or os.environ.get("ANIME_DISCOVERY_TOKEN")
    except (ImportError, KeyError):
        token = os.environ.get("ANIME_DISCOVERY_TOKEN")'''
    s = s.replace(old, new, 1)
    api.write_text(s)

s = api.read_text()
if "@app.get('/_internal/routes'" not in s:
    s += '''\n\n@app.get('/_internal/routes', dependencies=[Depends(authenticate)])
def internal_routes():
    """Authenticated route discovery, without enabling public OpenAPI."""
    return [{'methods': sorted(route.methods), 'path': route.path}
            for route in app.routes if hasattr(route, 'methods')]
'''
    api.write_text(s)
print('Config manager and controller patched. Restart controller once after migrating its existing token.')
