#!/usr/bin/env python3
"""Create/remove one isolated synthetic NEEDS_REVIEW inbox row. No network/torrent operations."""
import json, os, sqlite3, sys, time
from pathlib import Path
DB=Path(os.getenv('ANIME_DISCOVERY_INBOX_DB','/var/lib/anime-discovery-inbox/inbox.db'))
RES=Path(os.getenv('ANIME_REVIEW_RESOLUTIONS','/var/lib/anime-discovery/review-resolutions.json'))
STATE=Path(os.getenv('ANIME_NOTIFY_STATE','/var/lib/anime-discovery/ntfy-reminders.json'))
GUID='anime-discovery-review-smoke-test-20261017'
NAME='[TEST ONLY] Anime Discovery Needs Review notification test'
HASH='0'*40

def find(db):
    return db.execute('SELECT id,status FROM notifications WHERE source=? AND source_guid=?',('smoke-test',GUID)).fetchone()

def remove_state(path, ident):
    try: data=json.loads(path.read_text())
    except (OSError, ValueError): return
    if not isinstance(data,dict) or ident not in data:return
    del data[ident]
    tmp=path.with_name(path.name+'.smoke-tmp')
    with tmp.open('w') as f:json.dump(data,f);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,path)

def main():
    if len(sys.argv)!=2 or sys.argv[1] not in ('start','cleanup'):
        raise SystemExit('Usage: python3 review_smoke_test.py start|cleanup')
    if not DB.is_file() or DB.is_symlink():raise SystemExit('Inbox database missing or symlink: '+str(DB))
    with sqlite3.connect(str(DB),timeout=10) as db:
        row=find(db)
        if sys.argv[1]=='start':
            if row:raise SystemExit('Test row already exists (#%s). Run cleanup first.'%row[0])
            cur=db.execute('INSERT INTO notifications(source,release_name,source_guid,info_hash,received_at,status) VALUES (?,?,?,?,?,?)',('smoke-test',NAME,GUID,HASH,int(time.time()),'NEEDS_REVIEW'))
            ident=str(cur.lastrowid)
            print('Created synthetic NEEDS_REVIEW inbox #'+ident+'. Refresh dashboard; wait up to 2 minutes for ntfy.')
        else:
            if not row:print('No test row found; nothing to remove.');return
            ident=str(row[0])
            db.execute('DELETE FROM notifications WHERE id=? AND source=? AND source_guid=? AND release_name=? AND info_hash=?',(row[0],'smoke-test',GUID,NAME,HASH))
            print('Removed test inbox #'+ident)
    if sys.argv[1]=='cleanup':
        remove_state(RES,ident);remove_state(STATE,ident)
        print('Cleared test-only resolution and reminder records, if present. No real releases changed.')
if __name__=='__main__':main()
