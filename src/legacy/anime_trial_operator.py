#!/usr/bin/env python3
"""Conservative operator-controlled first live acquisition from Autobrr inbox.

Does not modify controller, receiver, existing torrents, or delete torrents.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import sqlite3
import sys

from qb_trial_add_adapter import QBTrialAdd, validate_magnet
from anime_config_runtime import get as config_get

INBOX = Path('/var/lib/anime-discovery-inbox/inbox.db')
JOURNAL = Path('/var/lib/anime-discovery/operator-add-journal.jsonl')


def notification(identifier):
    uri = 'file:{}?mode=ro'.format(INBOX)
    with sqlite3.connect(uri, uri=True, timeout=5) as db:
        db.row_factory = sqlite3.Row
        row = db.execute('SELECT id,source,release_name,source_guid,info_hash,status,received_at FROM notifications WHERE id=?', (identifier,)).fetchone()
    if not row:
        raise RuntimeError('Inbox notification not found')
    return dict(row)


def list_notifications(limit):
    with sqlite3.connect('file:{}?mode=ro'.format(INBOX), uri=True, timeout=5) as db:
        for item in db.execute('SELECT id,source,release_name,info_hash,status FROM notifications ORDER BY id DESC LIMIT ?', (limit,)):
            print(f'#{item[0]} [{item[1]}] {item[2]}\n    hash={item[3]} status={item[4]}')


def client():
    user = config_get('qbittorrent.username')
    password = config_get('qbittorrent.password')
    if not user or not password:
        raise RuntimeError('Configure qbittorrent.username and qbittorrent.password using anime_discovery.py settings; do not paste credentials here')
    qb = QBTrialAdd('http://127.0.0.1:8080', user, password)
    qb.login()
    return qb


def journal(entry):
    JOURNAL.parent.mkdir(parents=True, exist_ok=True)
    with JOURNAL.open('a', encoding='utf-8') as out:
        os.chmod(JOURNAL, 0o600)
        out.write(json.dumps(entry, sort_keys=True) + '\n')
        out.flush()
        os.fsync(out.fileno())


def add(identifier, magnet, confirmation):
    item = notification(identifier)
    if item['status'] != 'UNTRUSTED':
        raise RuntimeError('Unexpected inbox status; refusing add')
    h = item['info_hash'].lower()
    validate_magnet(magnet, h)
    if confirmation != h:
        raise RuntimeError('Approval requires typing the exact 40-character infohash')
    qb = client()
    inventory = qb.torrents()
    if any(t.torrent_hash == h for t in inventory):
        raise RuntimeError('Torrent already exists in qBittorrent; refusing to touch it')
    print('qB version:', qb.version())
    print('Existing torrent count:', len(inventory))
    print('Release:', item['release_name'])
    print('Expected hash:', h)
    print('Adding PAUSED to /mnt/media/Torrents/anime-trial (will not start downloading)')
    journal({'at': datetime.datetime.now(datetime.timezone.utc).isoformat(), 'event': 'ADD_INTENT', 'id': identifier, 'hash': h, 'inventory_before': len(inventory)})
    try:
        qb.add_trial_magnet(magnet, h, allow_external_write=True)
    except Exception:
        journal({'event': 'ADD_UNCERTAIN', 'id': identifier, 'hash': h})
        raise
    post = qb.torrents()
    matching = [t for t in post if t.torrent_hash == h]
    journal({'event': 'ADD_RESULT', 'id': identifier, 'hash': h, 'found': len(matching) == 1, 'inventory_after': len(post)})
    if len(matching) != 1:
        raise RuntimeError('qB accepted add but torrent not visible yet. Do not retry; inspect qB Web UI.')
    print('SUCCESS: trial torrent added PAUSED. Open qB Web UI and inspect it before resuming.')
    print('No existing torrents were paused, deleted, or modified by this tool.')


def main():
    parser = argparse.ArgumentParser(description='Conservative Anime Discovery live torrent add')
    subs = parser.add_subparsers(dest='action', required=True)
    show = subs.add_parser('inbox', help='List incoming releases without making changes')
    show.add_argument('--limit', type=int, default=15)
    launch = subs.add_parser('add-paused', help='Explicitly add one selected magnet in paused state')
    launch.add_argument('--id', type=int, required=True)
    launch.add_argument('--magnet', required=True)
    launch.add_argument('--confirm-hash', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'inbox':
            list_notifications(max(1, min(args.limit, 100)))
        else:
            add(args.id, args.magnet, args.confirm_hash)
    except (RuntimeError, ValueError, sqlite3.Error, OSError) as error:
        print('STOP:', error, file=sys.stderr)
        sys.exit(1)

if __name__ == '__main__':
    main()
