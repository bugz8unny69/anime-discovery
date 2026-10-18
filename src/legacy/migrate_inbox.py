#!/usr/bin/env python3
"""Offline SQLite backup to centralized location. Stop inbox and dashboard first."""
import os, sqlite3, subprocess, sys
from pathlib import Path
from anime_config_runtime import data_path

def main():
    source = Path('/var/lib/anime-discovery-inbox/inbox.db')
    target = data_path('inbox.db')
    for unit in ('anime-autobrr-inbox.service', 'anime-dashboard.service'):
        if subprocess.run(['systemctl','is-active','--quiet',unit]).returncode == 0:
            sys.exit(f'STOP: {unit} is active; stop both services first')
    if not source.is_file() or source.is_symlink(): sys.exit('STOP: original inbox DB missing or symlink')
    if target.exists() or target.is_symlink(): sys.exit('STOP: destination already exists; refusing overwrite')
    if not target.parent.is_dir(): sys.exit('STOP: configured data directory missing')
    src = sqlite3.connect(f'file:{source}?mode=ro', uri=True)
    try:
        old_count = src.execute('SELECT count(*) FROM notifications').fetchone()[0]
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
            new_count = dst.execute('SELECT count(*) FROM notifications').fetchone()[0]
            integrity = dst.execute('PRAGMA integrity_check').fetchone()[0]
        finally: dst.close()
        if integrity != 'ok' or old_count != new_count:
            target.unlink(missing_ok=True)
            sys.exit('STOP: migration verification failed')
        import pwd
        user = pwd.getpwnam('anime-discovery')
        os.chown(target, user.pw_uid, user.pw_gid)
        os.chmod(target, 0o600)
        print(f'Migrated {old_count} notifications to {target}; original retained at {source}')
    finally: src.close()
if __name__ == '__main__': main()
