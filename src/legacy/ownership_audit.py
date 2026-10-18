"""Read-only correlation of controller attempts and qB inventory; NEVER grants ownership."""
import argparse
import getpass
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from anime_service_adapters import QBittorrentReadOnly
from production_edges import snapshot_to_disposable

class AuditBlocked(RuntimeError):
    pass

def audit_attempts(rows, torrents):
    """Rows: (id,series_id,season,episode,hash,status). No hashes in report."""
    inventory = {}
    for t in torrents:
        h = t.torrent_hash.lower()
        if h in inventory:
            raise AuditBlocked('duplicate qB inventory hash')
        inventory[h] = t
    seen = set()
    report = {'attempts': 0, 'present_in_qb': 0, 'absent_from_qb': 0,
              'invalid_or_ambiguous': 0, 'superseded': 0,
              'ownership_verified': False, 'cancellation_enabled': False}
    latest = {}
    for row in rows:
        aid, sid, season, episode, h, status = row
        if type(aid) is int and type(sid) is int and type(season) is int and type(episode) is int:
            key = (sid,season,episode)
            latest[key] = max(aid, latest.get(key,0))
    for row in rows:
        report['attempts'] += 1
        aid,sid,season,episode,h,status = row
        valid = (all(type(x) is int and x > 0 for x in (aid,sid,season,episode))
                 and isinstance(h,str) and len(h)==40
                 and all(c in '0123456789abcdef' for c in h.lower()))
        if not valid or h.lower() in seen:
            report['invalid_or_ambiguous'] += 1
            continue
        seen.add(h.lower())
        if aid != latest[(sid,season,episode)]:
            report['superseded'] += 1
        if h.lower() in inventory:
            report['present_in_qb'] += 1
        else:
            report['absent_from_qb'] += 1
    return report

def snapshot_rows(db_path):
    """Use SQLite online backup; source is never opened writable."""
    with tempfile.TemporaryDirectory(prefix='anime-ownership-audit-') as td:
        dst = Path(td) / 'snapshot.db'
        snapshot_to_disposable(str(Path(db_path).resolve()), str(dst))
        with sqlite3.connect('file:{}?mode=ro'.format(dst), uri=True) as db:
            columns = {r[1] for r in db.execute('PRAGMA table_info(download_attempts)')}
            required = {'id','series_id','season','episode','torrent_hash','status'}
            if not required.issubset(columns):
                raise AuditBlocked('download_attempts schema mismatch')
            return db.execute('SELECT id,series_id,season,episode,torrent_hash,status FROM download_attempts').fetchall()

def main():
    p = argparse.ArgumentParser(description='Read-only qB/controller correlation; no ownership grants')
    p.add_argument('--db', default='/var/lib/anime-discovery/controller.db')
    args = p.parse_args()
    rows = snapshot_rows(args.db)
    username = os.environ.get('QBITTORRENT_USERNAME') or input('qBittorrent username: ')
    password = os.environ.get('QBITTORRENT_PASSWORD') or getpass.getpass('qBittorrent password: ')
    qb = QBittorrentReadOnly(os.environ.get('QBITTORRENT_URL','http://127.0.0.1:8080'), username,password)
    qb.login()
    torrents = qb.torrents()
    result = audit_attempts(rows,torrents)
    result['qb_inventory_count'] = len(torrents)
    result['production_database_modified'] = False
    print(json.dumps(result,indent=2,sort_keys=True))

if __name__ == '__main__':
    main()
