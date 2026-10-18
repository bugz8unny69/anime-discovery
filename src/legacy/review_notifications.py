#!/usr/bin/env python3
"""Read-only inbox monitor with persistent ntfy reminders for explicit NEEDS_REVIEW rows.
Does not change torrent, inbox, dashboard decision, or Sonarr state.
"""
import json, os, sqlite3, time, urllib.request, urllib.parse, threading
from datetime import datetime
from pathlib import Path
from anime_config_runtime import get as setting

INBOX=Path(os.getenv('ANIME_DISCOVERY_INBOX_DB','/var/lib/anime-discovery-inbox/inbox.db'))
RESOLUTIONS=Path(os.getenv('ANIME_REVIEW_RESOLUTIONS','/var/lib/anime-discovery/review-resolutions.json'))
STATE=Path(os.getenv('ANIME_NOTIFY_STATE','/var/lib/anime-discovery/ntfy-reminders.json'))
# Read live settings at point of use; do not cache credentials or endpoints.
SERVER_DEFAULT='https://ntfy.sh'
TOPIC_DEFAULT=''
PUBLIC_URL_DEFAULT='https://animeds.bugzbunny.net'
def reminder_interval():
    return max(3600, int(setting('ntfy.reminder_hours'))*3600)
POLL=max(30,int(os.getenv('ANIME_REVIEW_POLL_SECONDS','120')))
QUIET=os.getenv('ANIME_NOTIFY_QUIET_HOURS','').strip()  # optional HH:MM-HH:MM, local time


def in_quiet_hours():
    if not QUIET:return False
    start,end=QUIET.split('-',1)
    def minutes(s):
        h,m=map(int,s.split(':'))
        if not 0<=h<=23 or not 0<=m<=59:raise ValueError('Invalid quiet hour')
        return h*60+m
    a,b=minutes(start),minutes(end)
    now=datetime.now(); t=now.hour*60+now.minute
    return (a<=t<b) if a<b else (t>=a or t<b) if a>b else False


def pending():
    if not INBOX.is_file():return {}
    with sqlite3.connect('file:'+urllib.parse.quote(str(INBOX))+'?mode=ro',uri=True,timeout=3) as db:
        rows=db.execute("SELECT id,release_name,status FROM notifications WHERE UPPER(status) IN ('NEEDS_REVIEW','NEEDS REVIEW')").fetchall()
    try:
        resolved=json.loads(RESOLUTIONS.read_text())
    except (FileNotFoundError,ValueError):resolved={}
    return {str(i):name for i,name,_ in rows if str(i) not in resolved}


def load():
    try:
        value=json.loads(STATE.read_text());return value if isinstance(value,dict) else {}
    except (FileNotFoundError,ValueError):return {}


def save(data):
    STATE.parent.mkdir(parents=True,exist_ok=True)
    tmp=STATE.with_name(STATE.name+'.tmp')
    with tmp.open('w') as f:
        json.dump(data,f);f.flush();os.fsync(f.fileno())
    os.chmod(tmp,0o600);os.replace(tmp,STATE)


def notify(name,identifier,reminder):
    topic=setting('ntfy.topic').strip()
    server=(setting('ntfy.server') or '').rstrip('/')
    public_url=setting('dashboard.public_url').rstrip('/')
    if not topic:raise RuntimeError('ntfy topic is not set')
    if not server.startswith('https://'):raise RuntimeError('Configure an HTTPS ntfy server before notifications')
    if not public_url.startswith('https://'):raise RuntimeError('Dashboard public URL must use HTTPS')
    url=server+'/'+urllib.parse.quote(topic,safe='')
    link=public_url+'/?tab=needs-review&item='+urllib.parse.quote(identifier)
    title='Anime Discovery: Review reminder' if reminder else 'Anime Discovery: Needs Review'
    body=f'{name}\nOpen Anime Discovery to review this release.'
    req=urllib.request.Request(url,data=body.encode(),method='POST',headers={
        'Title':title,'Priority':'default','Tags':'warning','Click':link,
        'Content-Type':'text/plain; charset=utf-8'})
    token=(setting('ntfy.token') or '').strip()
    if token:req.add_header('Authorization','Bearer '+token)
    with urllib.request.urlopen(req,timeout=12) as response:
        if response.status not in (200,201,202):raise RuntimeError('ntfy returned '+str(response.status))


def check_once(now=None):
    now=time.time() if now is None else now
    items=pending(); state=load()
    # Remove resolved entries, so re-entering review generates a fresh immediate alert.
    state={k:v for k,v in state.items() if k in items}
    if not in_quiet_hours():
        for key,name in items.items():
            last=state.get(key,{}).get('sent_at',0)
            if now-last>=reminder_interval():
                try:
                    notify(name,key,bool(last))
                except Exception as exc:
                    print('ntfy delivery failed for inbox #'+key+': '+str(exc),flush=True)
                else:
                    state[key]={'sent_at':now}
    save(state)


def main():
    if QUIET:in_quiet_hours()
    print('ntfy review monitor running; live settings enabled',flush=True)
    while True:
        try:check_once()
        except Exception as exc:print('ntfy monitor error: '+str(exc),flush=True)
        time.sleep(POLL)

if __name__=='__main__':main()
