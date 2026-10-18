#!/usr/bin/env python3
"""Conservative trial-library staging, rejection cleanup, and Jellyfin refresh.
Does not interact with qBittorrent or the controller database.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import tempfile
import urllib.request

ROOT = Path('/mnt/media/Anime-Trial')

def safe_show(name):
    if not name or name in ('.', '..') or '/' in name or '\\' in name or '\x00' in name:
        raise ValueError('Show must be one plain directory name')
    return name

def ensure_root():
    if ROOT.is_symlink() or not ROOT.is_dir():
        raise RuntimeError('Trial library root is missing or a symlink')
    return ROOT.resolve(strict=True)

def show_dir(name):
    root = ensure_root()
    show = root / safe_show(name)
    if show.is_symlink() or (show.exists() and not show.is_dir()):
        raise RuntimeError('Show directory is unsafe')
    return show

def scan():
    from anime_config_runtime import get
    url = get('jellyfin.url').rstrip('/')
    if not url:
        url = os.environ.get('ANIME_JELLYFIN_URL', '').rstrip('/')
    key = get('jellyfin.api_key')
    if not url or not key:
        print('SCAN_PENDING: configure jellyfin.url and jellyfin.api_key', file=sys.stderr)
        return False
    if not url.startswith(('http://', 'https://')):
        raise RuntimeError('Invalid Jellyfin URL')
    req = urllib.request.Request(url + '/Library/Refresh', data=b'', method='POST', headers={'X-Emby-Token': key})
    with urllib.request.urlopen(req, timeout=20) as response:
        if response.status not in (200, 202, 204):
            raise RuntimeError('Jellyfin refresh HTTP ' + str(response.status))
    print('SCAN_REQUESTED: Jellyfin accepted refresh request (completion not verified)')
    return True

def stage(args):
    src = Path(args.source)
    if src.is_symlink() or not src.is_file() or not stat.S_ISREG(src.stat().st_mode):
        raise RuntimeError('Source must be a regular, non-symlink file')
    if src.suffix.lower() not in ('.mkv', '.mp4'):
        raise RuntimeError('Unsupported video extension')
    destdir = show_dir(args.show) / f'Season {args.season:02d}'
    dest = destdir / f'{args.show} - S{args.season:02d}E{args.episode:02d}{src.suffix.lower()}'
    if dest.exists() or dest.is_symlink():
        raise RuntimeError('Destination exists; refusing overwrite')
    if not args.execute:
        print('DRY RUN: stage', src, '->', dest)
        return
    destdir.mkdir(parents=True, exist_ok=True)
    if destdir.is_symlink():
        raise RuntimeError('Unsafe season directory')
    fd, tempname = tempfile.mkstemp(prefix='.incoming-', suffix='.part', dir=destdir)
    try:
        with os.fdopen(fd, 'wb') as out, src.open('rb') as inp:
            shutil.copyfileobj(inp, out, 1024 * 1024)
            out.flush()
            os.fsync(out.fileno())
        if os.stat(tempname).st_size != src.stat().st_size:
            raise RuntimeError('Copied size mismatch')
        os.link(tempname, dest)  # atomic no-overwrite publish on same filesystem
        print('STAGED:', dest)
    finally:
        os.unlink(tempname)
    scan()

def reject(args):
    show = show_dir(args.show)
    if not show.exists():
        print('NO_TRIAL_FILES:', show)
        return
    files = []
    for base, dirs, names in os.walk(show, followlinks=False):
        for d in dirs:
            if (Path(base) / d).is_symlink():
                raise RuntimeError('Refusing cleanup with symlinked directory')
        for name in names:
            path = Path(base) / name
            if path.is_symlink() or not stat.S_ISREG(path.lstat().st_mode):
                raise RuntimeError('Refusing cleanup with non-regular file')
            files.append(path)
    print('TRIAL FILES:', *map(str, files), sep='\n  ')
    if not args.execute:
        print('DRY RUN: no files removed')
        return
    if args.confirm_show != args.show:
        raise RuntimeError('Pass --confirm-show with the exact show name to remove trial files')
    for path in files:
        path.unlink()
    for base, dirs, names in os.walk(show, topdown=False):
        for d in dirs:
            (Path(base) / d).rmdir()
    show.rmdir()
    print('REMOVED_TRIAL_COPY:', show)
    if not args.no_scan:
        scan()

def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    a = sub.add_parser('stage', help='Copy one verified episode; refresh Jellyfin after publish')
    a.add_argument('--show', required=True)
    a.add_argument('--source', required=True)
    a.add_argument('--season', type=int, default=1)
    a.add_argument('--episode', type=int, required=True)
    a.add_argument('--execute', action='store_true')
    b = sub.add_parser('reject', help='Remove trial copies only; refresh Jellyfin')
    b.add_argument('--show', required=True)
    b.add_argument('--confirm-show')
    b.add_argument('--execute', action='store_true')
    b.add_argument('--no-scan', action='store_true', help='Batch operation: request refresh separately after all removals')
    sub.add_parser('scan', help='Request Jellyfin library refresh')
    args = p.parse_args()
    if args.command == 'stage':
        if not 1 <= args.season <= 99 or not 1 <= args.episode <= 999:
            raise RuntimeError('Invalid episode number')
        stage(args)
    elif args.command == 'reject':
        reject(args)
    else:
        scan()

if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('STOP:', exc, file=sys.stderr)
        sys.exit(1)
