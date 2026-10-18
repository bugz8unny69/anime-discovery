#!/usr/bin/env python3
"""Fail-closed V22 pilot controller. No network or torrent/sonarr writes."""
import argparse,json,sqlite3,sys
from pathlib import Path
HASH='175d53091888f5cd7e04f1bc6458034f0018e787'
SHADOW=Path('/var/lib/anime-discovery/identity-confidence-v15.db')
INBOX=Path('/var/lib/anime-discovery/inbox.db')
TRIAL=Path('/var/lib/anime-discovery/v18-episode2-trial.db')

def evidence(shadow=SHADOW,inbox=INBOX,trial=TRIAL):
    out={'hash':HASH,'authorization':'BLOCKED','reasons':[],'notification_ids':[],'trial_action':None,'eligible_for_trial_stage':False}
    if not inbox.is_file():out['reasons'].append('INBOX_DB_MISSING');return out
    try:
        with sqlite3.connect(f'file:{inbox}?mode=ro',uri=True) as db:
            ids=[r[0] for r in db.execute('SELECT id FROM notifications WHERE lower(info_hash)=? ORDER BY id',(HASH,))]
        out['notification_ids']=ids
        if not ids:out['reasons'].append('NOT_IN_INBOX')
    except sqlite3.Error as e:out['reasons'].append('INBOX_READ_FAILED');return out
    if trial.is_file():
        try:
            with sqlite3.connect(f'file:{trial}?mode=ro',uri=True) as db:
                r=db.execute('SELECT action FROM trial_events WHERE torrent_hash=? ORDER BY id DESC LIMIT 1',(HASH,)).fetchone()
                out['trial_action']=r[0] if r else None
        except sqlite3.Error:out['reasons'].append('TRIAL_STATE_UNAVAILABLE')
    else:out['reasons'].append('TRIAL_STATE_UNAVAILABLE')
    if out['trial_action']=='REJECTED':out['reasons'].append('REJECTED_REPLAY_BLOCK')
    if not shadow.is_file():out['reasons'].append('VERIFICATION_DB_MISSING');return out
    verified=[]
    try:
        with sqlite3.connect(f'file:{shadow}?mode=ro',uri=True) as db:
            for nid in ids:
                r=db.execute('SELECT verified,evidence_json FROM episode_verification_v16 WHERE notification_id=?',(nid,)).fetchone()
                if not r:continue
                doc=json.loads(r[1]);verified.append({'id':nid,'verified':r[0]==1 and doc.get('episode_identity_verified') is True,'decision':doc.get('decision'),'blockers':doc.get('blockers',[])})
    except (sqlite3.Error,ValueError,TypeError):out['reasons'].append('VERIFICATION_READ_FAILED');return out
    out['verifications']=verified
    if not any(v['verified'] and not v['blockers'] for v in verified):out['reasons'].append('EPISODE_IDENTITY_NOT_VERIFIED')
    if out['trial_action'] in ('RESTORED','STAGED','STAGED_EXISTING_VERIFIED'):
        out['reasons'].append('TRIAL_ALREADY_OWNED')
    out['eligible_for_trial_stage']=not out['reasons']
    out['authorization']='TRIAL_STAGE_ONLY' if out['eligible_for_trial_stage'] else 'BLOCKED'
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=['status','stage']);p.add_argument('--apply',action='store_true');a=p.parse_args()
    result=evidence();print(json.dumps(result,indent=2))
    if a.action=='stage':
        if not a.apply or not result['eligible_for_trial_stage']:
            print('STAGE_REFUSED: require --apply and verified episode evidence',file=sys.stderr);return 2
        # Revalidate in trial_episode2.py: checksum, backup, NAS mount and rejection state.
        import trial_episode2
        trial_episode2.stage()
    return 0
if __name__=='__main__':sys.exit(main())
