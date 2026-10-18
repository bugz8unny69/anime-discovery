#!/usr/bin/env python3
"""Anime Discovery configuration CLI. Standard library only; no service restart."""
import argparse
import fcntl
import getpass
import json
import os
from pathlib import Path
import re
import sys
import tempfile

ROOT = Path(os.environ.get('ANIME_CONFIG_DIR', '/etc/anime-discovery'))
SCHEMA = {
 'discovery.data_dir': ('path', '/var/lib/anime-discovery', 'restart all services; migrate data first'),
 'controller.bind_host': ('loopback', '127.0.0.1', 'controller restart'),
 'controller.bind_port': ('int:1024:65535', 8765, 'controller restart'),
 'dashboard.bind_host': ('loopback', '127.0.0.1', 'dashboard restart'),
 'inbox.bind_host': ('loopback', '127.0.0.1', 'inbox restart'),
 'inbox.bind_port': ('int:1024:65535', 18766, 'inbox restart'),
 'controller.api_token': ('secret', None, 'next request'),
 'tvdb.enabled': ('bool', False, 'next lookup'),
 'tvdb.api_key': ('secret', None, 'next lookup'),
 'ntfy.server': ('url', '', 'next worker cycle'),
 'ntfy.topic': ('str', 'anime-discovery', 'next worker cycle'),
 'ntfy.token': ('secret', None, 'next worker cycle'),
 'ntfy.reminder_hours': ('int:1:720', 24, 'next worker cycle'),
 'dashboard.public_url': ('url', 'https://animeds.bugzbunny.net', 'next request'),
 'dashboard.bind_port': ('int:1024:65535', 18767, 'dashboard restart'),
 'jellyfin.url': ('url', '', 'next request'),
 'jellyfin.api_key': ('secret', None, 'next request'),
 'qbittorrent.username': ('str', '', 'next client initialization'),
 'qbittorrent.password': ('secret', None, 'next client initialization'),
 'discovery.max_trial_episodes': ('int:1:6', 6, 'next controller cycle'),
 'discovery.downloads_enabled': ('bool', False, 'controller restart; safety gates still apply'),
 'prowlarr.url': ('url', '', 'next historical search'),
 'prowlarr.api_key': ('secret', None, 'next historical search'),
}
ENV_MAP = {'tvdb.api_key':'ANIME_TVDB_API_KEY','ntfy.server':'ANIME_NTFY_SERVER','ntfy.topic':'ANIME_NTFY_TOPIC','ntfy.token':'ANIME_NTFY_TOKEN','ntfy.reminder_hours':'ANIME_REVIEW_REMINDER_HOURS','dashboard.public_url':'ANIME_DASHBOARD_PUBLIC_URL','jellyfin.api_key':'ANIME_JELLYFIN_API_KEY','qbittorrent.username':'ANIME_QB_USERNAME','qbittorrent.password':'ANIME_QB_PASSWORD'}

def validate(key, value):
    if key not in SCHEMA: raise ValueError('Unknown setting: '+key)
    typ = SCHEMA[key][0]
    if typ == 'secret':
        if not value: raise ValueError('Secret cannot be empty')
        return value
    if typ == 'bool':
        if str(value).lower() not in ('true','false'): raise ValueError('Expected true or false')
        return str(value).lower() == 'true'
    if typ.startswith('int:'):
        _, lo, hi = typ.split(':')
        try: number = int(value)
        except (ValueError,TypeError): raise ValueError('Expected integer')
        if not int(lo) <= number <= int(hi): raise ValueError('Expected integer between '+lo+' and '+hi)
        return number
    if typ == 'loopback':
        if value not in ('127.0.0.1', '::1'): raise ValueError('Only loopback bind hosts are allowed')
        return value
    if typ == 'path':
        if not isinstance(value, str) or not value.startswith('/') or not Path(value).is_absolute() or '..' in Path(value).parts or value == '/':
            raise ValueError('Expected safe absolute data directory')
        return str(Path(value))
    if typ == 'url' and value and not re.fullmatch(r'https?://[^\s/]+(?:/[^\s]*)?', value): raise ValueError('Expected http(s) URL')
    if not isinstance(value, str): raise ValueError('Expected string')
    return value

def load(name):
    path = ROOT / name
    if not path.exists(): return {}
    data = json.loads(path.read_text())
    if not isinstance(data, dict): raise ValueError('Invalid config file '+str(path))
    return data

def atomic_write(path, data, mode):
    ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.'+path.name+'.', dir=ROOT)
    try:
        os.fchmod(fd, mode)
        with os.fdopen(fd, 'w') as file:
            json.dump(data, file, indent=2, sort_keys=True)
            file.write('\n'); file.flush(); os.fsync(file.fileno())
        os.replace(tmp, path)
        directory = os.open(ROOT, os.O_RDONLY)
        try: os.fsync(directory)
        finally: os.close(directory)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def update(key, value=None, unset=False):
    if key not in SCHEMA: raise ValueError('Unknown setting: '+key)
    secret = SCHEMA[key][0] == 'secret'
    filename = 'secrets.json' if secret else 'config.json'
    ROOT.mkdir(mode=0o750, parents=True, exist_ok=True)
    with (ROOT / '.config.lock').open('a+') as lock:
        os.chmod(ROOT / '.config.lock', 0o600)
        fcntl.flock(lock, fcntl.LOCK_EX)
        data = load(filename)
        if unset: data.pop(key, None)
        else: data[key] = validate(key, value)
        atomic_write(ROOT / filename, data, 0o600 if secret else 0o640)
    print(f'{key}: '+('removed (default restored)' if unset else '[configured]' if secret else str(data[key])))
    print('Activation: '+SCHEMA[key][2]+' (only after service integration)')

def effective(key):
    secret = SCHEMA[key][0] == 'secret'
    data = load('secrets.json' if secret else 'config.json')
    if key in data: return data[key], 'file'
    return SCHEMA[key][1], 'default'

def main():
    parser = argparse.ArgumentParser(description='Anime Discovery configuration manager')
    parser.add_argument('--add-setting', metavar='KEY=VALUE')
    parser.add_argument('--remove-setting', metavar='KEY')
    subs = parser.add_subparsers(dest='command')
    settings = subs.add_parser('settings'); ops = settings.add_subparsers(dest='operation', required=True)
    for cmd in ('list','status','migrate-preview'): ops.add_parser(cmd)
    for cmd in ('get','unset','set-secret'): ops.add_parser(cmd).add_argument('key')
    setp = ops.add_parser('set'); setp.add_argument('assignment')
    args = parser.parse_args()
    try:
        if args.add_setting:
            key, sep, value = args.add_setting.partition('=')
            if not sep: raise ValueError('Expected KEY=VALUE')
            if SCHEMA.get(key, ('',))[0] == 'secret': raise ValueError('Use settings set-secret to avoid shell history leaks')
            update(key, value); return
        if args.remove_setting: update(args.remove_setting, unset=True); return
        if args.command != 'settings': parser.print_help(); return
        op = args.operation
        if op == 'set':
            key, sep, value = args.assignment.partition('=')
            if not sep: raise ValueError('Expected KEY=VALUE')
            if SCHEMA.get(key, ('',))[0] == 'secret': raise ValueError('Use set-secret')
            update(key, value)
        elif op == 'set-secret':
            if SCHEMA.get(args.key, ('',))[0] != 'secret': raise ValueError('Not a secret setting')
            first = getpass.getpass('Enter '+args.key+': ')
            second = getpass.getpass('Confirm: ')
            if first != second: raise ValueError('Values do not match')
            update(args.key, first)
        elif op == 'unset': update(args.key, unset=True)
        elif op == 'get':
            if args.key not in SCHEMA: raise ValueError('Unknown setting')
            val, source = effective(args.key)
            print(args.key+' = '+('[configured]' if val else '[not configured]') if SCHEMA[args.key][0]=='secret' else f'{args.key} = {val!r} ({source})')
        elif op == 'list':
            for key in sorted(SCHEMA):
                val, source = effective(key)
                display = '[configured]' if val else '[not configured]' if SCHEMA[key][0]=='secret' else repr(val)
                if SCHEMA[key][0] != 'secret': display = repr(val)
                print(f'{key:36} {display:32} {source:8} {SCHEMA[key][2]}')
        elif op == 'status':
            print('Config directory:', ROOT)
            print('Registered settings:', len(SCHEMA))
            print('Service hot-reload integration: NOT INSTALLED; restart services after manual integration')
        elif op == 'migrate-preview':
            for key, env in sorted(ENV_MAP.items()):
                if env in os.environ:
                    print(f'{env} -> {key}: '+('[present, value hidden]' if SCHEMA[key][0]=='secret' else 'present'))
            print('Preview only; no environment values copied or modified.')
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print('Error:', exc, file=sys.stderr); sys.exit(2)

if __name__ == '__main__': main()
