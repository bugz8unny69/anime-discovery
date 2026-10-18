#!/usr/bin/env python3
"""Targeted Solo Leveling S01E02 trial filesystem exercise. No qBittorrent/Sonarr writes."""
import argparse, hashlib, json, os, shutil, sqlite3, stat, sys, time
from pathlib import Path

HASH='175d53091888f5cd7e04f1bc6458034f0018e787'
SHA='8ab69bfb688a6a06a25d9604c880d8bf130d7657ca5596b3854d3ef1f88a06a8'
NAME='[MiniDual ] S01E02-If I Had One More Chance (Dual).mkv'
SRC=Path('/mnt/media/Torrents/anime')/NAME
BACKUP=Path('/mnt/media/Torrents/anime-discovery-test-backups/solo-leveling-s01e02-20261017-130524')/NAME
TRIALDIR=Path('/mnt/media/Anime-Trial')
TRIAL=TRIALDIR/NAME
STATE=Path('/var/lib/anime-discovery/v18-episode2-trial.db')
SIZE=409153994

def digest(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''): h.update(b)
    return h.hexdigest()

def safe_file(p):
    if p.is_symlink() or not p.is_file() or p.stat().st_size!=SIZE or digest(p)!=SHA:
        raise RuntimeError(f'File missing, unsafe or checksum mismatch: {p}')

def check_paths():
    for p in (SRC,BACKUP): safe_file(p)
    if TRIALDIR.is_symlink() or not TRIALDIR.is_dir(): raise RuntimeError('Trial directory missing or symlink')
    if not TRIALDIR.resolve()==Path('/mnt/media/Anime-Trial').resolve(): raise RuntimeError('Trial directory resolution changed')
    if not os.path.ismount('/mnt/media'): raise RuntimeError('NAS /mnt/media is not mounted')

def connect():
    STATE.parent.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect(STATE)
    db.execute('CREATE TABLE IF NOT EXISTS trial_events (id INTEGER PRIMARY KEY, at TEXT DEFAULT CURRENT_TIMESTAMP, torrent_hash TEXT NOT NULL, action TEXT NOT NULL, path TEXT NOT NULL, sha256 TEXT NOT NULL)')
    db.commit()
    return db

def record(db, action):
    db.execute('INSERT INTO trial_events(torrent_hash,action,path,sha256) VALUES(?,?,?,?)',(HASH,action,str(TRIAL),SHA)); db.commit()

def latest(db):
    row=db.execute('SELECT action FROM trial_events WHERE torrent_hash=? ORDER BY id DESC LIMIT 1',(HASH,)).fetchone()
    return row[0] if row else None

def stage():
    check_paths()
    db=connect()
    if TRIAL.is_symlink(): raise RuntimeError('Trial destination symlink refused')
    if TRIAL.exists():
        safe_file(TRIAL)
        if latest(db) in ('REJECTED',): raise RuntimeError('Rejected trial already exists; manual reconciliation required')
        print('TRIAL_ALREADY_PRESENT_AND_VERIFIED')
        if latest(db) is None: record(db,'STAGED_EXISTING_VERIFIED')
        return
    if latest(db)=='REJECTED': raise RuntimeError('Rejected: use restore, not stage')
    temp=TRIALDIR/(NAME+'.v18-staging-'+str(os.getpid()))
    if temp.exists() or temp.is_symlink(): raise RuntimeError('Temporary file exists')
    try:
        with BACKUP.open('rb') as src, temp.open('xb') as out: shutil.copyfileobj(src,out,4*1024*1024)
        safe_file(temp)
        os.replace(temp,TRIAL)
        record(db,'STAGED')
        print('TRIAL_STAGED_AND_VERIFIED',TRIAL)
    finally:
        if temp.exists(): temp.unlink()

def reject():
    check_paths()
    if not STATE.exists(): raise RuntimeError('No recorded ownership; refuse deletion')
    db=connect()
    if latest(db) not in ('STAGED','STAGED_EXISTING_VERIFIED','RESTORED'):
        raise RuntimeError('No active trial ownership record; refuse deletion')
    safe_file(TRIAL)
    # Only this exact recorded, checksum-matching trial path can be unlinked.
    TRIAL.unlink()
    record(db,'REJECTED')
    print('TRIAL_COPY_REMOVED_REJECTED; ORIGINAL_AND_BACKUP_PRESERVED')

def restore():
    check_paths()
    if not STATE.exists(): raise RuntimeError('No rejection history')
    db=connect()
    if latest(db)!='REJECTED': raise RuntimeError('Restore requires latest decision REJECTED')
    if TRIAL.exists() or TRIAL.is_symlink(): raise RuntimeError('Trial destination already exists')
    temp=TRIALDIR/(NAME+'.v18-restore-'+str(os.getpid()))
    if temp.exists() or temp.is_symlink(): raise RuntimeError('Temporary file exists')
    try:
        with BACKUP.open('rb') as src, temp.open('xb') as out: shutil.copyfileobj(src,out,4*1024*1024)
        safe_file(temp)
        os.replace(temp,TRIAL)
        record(db,'RESTORED')
        print('TRIAL_RESTORED_FROM_BACKUP; NO_DOWNLOAD_STARTED')
    finally:
        if temp.exists(): temp.unlink()

def status():
    print(json.dumps({'hash':HASH,'source':str(SRC),'backup':str(BACKUP),'trial':str(TRIAL),'trial_exists':TRIAL.is_file() and not TRIAL.is_symlink(),'latest_trial_action':latest(connect()) if STATE.exists() else None,'webhook_enforcement_installed':False,'sonarr_integration_installed':False,'automatic_approval_installed':False},indent=2))

if __name__=='__main__':
    p=argparse.ArgumentParser(); p.add_argument('action',choices=['stage','reject','restore','status']); a=p.parse_args()
    try: {'stage':stage,'reject':reject,'restore':restore,'status':status}[a.action]()
    except Exception as e: print('ERROR:',e,file=sys.stderr);sys.exit(1)
