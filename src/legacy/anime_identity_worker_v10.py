#!/usr/bin/env python3
"""Isolated V10 inbox watcher. Serial runs; persistent retry and no torrent access."""
import argparse
import fcntl
import json
import os
import sqlite3
import time
from pathlib import Path
from anime_identity_worker_v9 import saved_readonly, process

DATA=Path('/var/lib/anime-discovery')

def init(db):
    with sqlite3.connect(db) as c:
        c.execute('CREATE TABLE IF NOT EXISTS identity_queue (notification_id INTEGER PRIMARY KEY, last_action TEXT NOT NULL, attempts INTEGER NOT NULL, next_at REAL NOT NULL, updated_at REAL NOT NULL)')

def pending(db, inbox, now, limit):
    from anime_identity_worker_v9 import rows_readonly
    # Existing UNTRUSTED rows remain eligible; completed records are excluded.
    rows=rows_readonly(inbox, 100)
    with sqlite3.connect(db) as c:
        result=[]
        for nid,status in sorted(rows):
            if status!='UNTRUSTED': continue
            prior=c.execute('SELECT last_action,next_at FROM identity_queue WHERE notification_id=?',(nid,)).fetchone()
            if prior and (prior[0] in ('SERIES_ALREADY_PERSISTED_EPISODE_PENDING','INSERTED','UNCHANGED') or prior[1]>now): continue
            result.append(nid)
            if len(result)>=limit: break
        return result

def record(db,nid,action,now):
    with sqlite3.connect(db) as c:
        old=c.execute('SELECT attempts FROM identity_queue WHERE notification_id=?',(nid,)).fetchone()
        attempts=(old[0] if old else 0)+1
        done=action in ('SERIES_ALREADY_PERSISTED_EPISODE_PENDING','INSERTED','UNCHANGED')
        # Back off uncertain results rather than hammering external APIs.
        delay=0 if done else min(86400, 300*2**min(attempts-1,8))
        c.execute('INSERT INTO identity_queue VALUES(?,?,?,?,?) ON CONFLICT(notification_id) DO UPDATE SET last_action=excluded.last_action,attempts=excluded.attempts,next_at=excluded.next_at,updated_at=excluded.updated_at',(nid,action,attempts,now+delay,now))

def run_once(args):
    now=time.time()
    ids=pending(args.state_db,args.inbox,now,args.limit)
    output={'version':10,'mode':'MANUAL' if args.once else 'WATCH','downloads_enabled':False,'items':[]}
    for nid in ids:
        # No network lookup here: existing v9 lookup lacks per-request pacing.
        saved=saved_readonly(args.verified,nid)
        if saved:
            action='SERIES_ALREADY_PERSISTED_EPISODE_PENDING'
            item={'notification_id':nid,'action':action,'anidb_id':saved[0],'tvdb_id':saved[1]}
        else:
            action='NEW_IDENTITY_LOOKUP_PENDING_RATE_LIMIT_INTEGRATION'
            item={'notification_id':nid,'action':action,'eligible_for_acquisition':False}
        record(args.state_db,nid,action,now)
        output['items'].append(item)
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inbox',type=Path,default=DATA/'inbox.db')
    p.add_argument('--verified',type=Path,default=DATA/'verified-series.db')
    p.add_argument('--state-db',type=Path,default=DATA/'identity-queue-v10.db')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--once',action='store_true')
    p.add_argument('--watch',action='store_true')
    p.add_argument('--poll-seconds',type=int,default=2)
    p.add_argument('--limit',type=int,default=5)
    a=p.parse_args()
    if a.once==a.watch: p.error('Specify exactly one of --once or --watch')
    if not 1<=a.limit<=100 or not 1<=a.poll_seconds<=3600:p.error('invalid limits')
    a.state_db.parent.mkdir(parents=True,exist_ok=True)
    lock=a.state_db.with_suffix('.lock')
    with open(lock,'a+') as fd:
        fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
        init(a.state_db)
        while True:
            result=run_once(a)
            a.output.parent.mkdir(parents=True,exist_ok=True)
            a.output.write_text(json.dumps(result,indent=2)+'\n')
            print(json.dumps({'processed':len(result['items']),'actions':[x['action'] for x in result['items']]}),flush=True)
            if a.once:break
            time.sleep(a.poll_seconds)
if __name__=='__main__':main()
