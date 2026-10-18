#!/usr/bin/env python3
"""Explicit-target, authenticated client for Anime Discovery internal APIs."""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.parse
import urllib.request

CONFIG_DIR = Path(os.environ.get('ANIME_CONFIG_DIR', '/etc/anime-discovery'))
TARGETS = {'controller': ('http://127.0.0.1:8765', 'controller.api_token', 'ANIME_DISCOVERY_TOKEN')}

def load_token(target):
    _, key, env = TARGETS[target]
    path = CONFIG_DIR / 'secrets.json'
    if path.exists():
        data = json.loads(path.read_text())
        if not isinstance(data, dict):
            raise ValueError('Invalid secrets configuration')
        if data.get(key):
            return str(data[key])
    return os.environ.get(env, '')

def request(target, method, path, payload=None, timeout=15, verbose=False):
    if not path.startswith('/') or path.startswith('//') or any(c in path for c in '\r\n\\'):
        raise ValueError('Path must start with a single / and contain no control characters')
    base, _, _ = TARGETS[target]
    token = load_token(target)
    if not token:
        raise ValueError('Controller token missing. Run: python3 anime_discovery.py settings set-secret controller.api_token')
    url = base + path
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {'Authorization': 'Bearer ' + token, 'Accept': 'application/json'}
    if data is not None:
        headers['Content-Type'] = 'application/json'
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    if verbose:
        print(f'{method} {url} (Authorization: [redacted])', file=sys.stderr)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read(2_000_000).decode('utf-8', errors='replace')
            return response.status, body
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read(2_000_000).decode('utf-8', errors='replace')

def main(argv=None):
    parser = argparse.ArgumentParser(description='Anime Discovery service API client')
    parser.add_argument('target', choices=sorted(TARGETS))
    parser.add_argument('resource', choices=['api'])
    parser.add_argument('operation', choices=['get', 'post', 'put', 'patch', 'delete', 'routes', 'test'])
    parser.add_argument('path', nargs='?')
    parser.add_argument('--data', help='JSON request body (avoid putting secrets here)')
    parser.add_argument('--yes', action='store_true', help='Confirm a state-changing operation')
    parser.add_argument('--timeout', type=float, default=15)
    parser.add_argument('--verbose', action='store_true')
    args = parser.parse_args(argv)
    try:
        if not 0 < args.timeout <= 120:
            raise ValueError('Timeout must be between 0 and 120 seconds')
        if args.operation == 'routes':
            operations = [('GET', '/_internal/routes')]
        elif args.operation == 'test':
            operations = [('GET', '/health'), ('GET', '/identities'), ('GET', '/identities/evidence'), ('GET', '/_internal/routes')]
        else:
            if not args.path:
                parser.error('A path is required')
            operations = [(args.operation.upper(), args.path)]
        if args.operation in ('routes', 'test') and (args.path or args.data):
            parser.error('routes/test do not accept a path or body')
        if args.operation in ('post', 'put', 'patch', 'delete') and not args.yes:
            parser.error('State-changing requests require --yes')
        if args.data and args.operation in ('get', 'delete'):
            parser.error('--data not allowed for GET/DELETE')
        payload = json.loads(args.data) if args.data else None
        failed = False
        for method, path in operations:
            status, body = request(args.target, method, path, payload, args.timeout, args.verbose)
            if args.operation == 'test':
                print(f'{method} {path}: HTTP {status} {"PASS" if status == 200 else "FAIL"}')
            else:
                print(f'HTTP {status}')
                try:
                    print(json.dumps(json.loads(body), indent=2))
                except json.JSONDecodeError:
                    print(body[:4000])
            failed |= not (200 <= status < 300)
        return 1 if failed else 0
    except (ValueError, OSError, json.JSONDecodeError, urllib.error.URLError) as exc:
        print(f'Error: {exc}', file=sys.stderr)
        return 2

if __name__ == '__main__':
    sys.exit(main())
