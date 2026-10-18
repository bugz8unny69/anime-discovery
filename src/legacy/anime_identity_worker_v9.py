#!/usr/bin/env python3
"""Bounded inbox identity scan; never changes inbox/controller or performs acquisition."""
import argparse
import json
import sqlite3
from pathlib import Path
from anime_identity_decision_v7 import decide
from anime_identity_persistence_v8 import persist

DEFAULT_DATA = Path('/var/lib/anime-discovery')

def rows_readonly(path, limit):
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        return db.execute('SELECT id,status FROM notifications ORDER BY id DESC LIMIT ?', (limit,)).fetchall()

def saved_readonly(path, notification_id):
    if not Path(path).is_file():
        return None
    uri = Path(path).resolve().as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        try:
            return db.execute('SELECT anidb_id,tvdb_id,decision,episode_identity_verified,eligible_for_acquisition FROM verified_series_identity WHERE notification_id=?', (notification_id,)).fetchone()
        except sqlite3.OperationalError as exc:
            raise RuntimeError('Verified-series database schema unavailable') from exc

def process(inbox, verified, limit, apply_series=False, episode_runner=None):
    output = {'version':9,'mode':'APPLY_SERIES_ONLY' if apply_series else 'READ_ONLY', 'downloads_enabled':False,
              'inbox_modified':False,'controller_modified':False,'notifications_sent':False,'items':[]}
    for notification_id, status in rows_readonly(inbox, limit):
        item = {'notification_id':notification_id,'inbox_status':status,'episode_identity_verified':False,
                'eligible_for_acquisition':False}
        try:
            if status != 'UNTRUSTED':
                item['action'] = 'SKIPPED_NON_UNTRUSTED'
            else:
                saved = saved_readonly(verified, notification_id)
                if saved:
                    item.update(action='SERIES_ALREADY_PERSISTED_EPISODE_PENDING', anidb_id=saved[0], tvdb_id=saved[1])
                    if saved[3] or saved[4]:
                        raise RuntimeError('Stored identity unexpectedly claims episode approval')
                elif episode_runner is None:
                    item['action'] = 'NO_RUNNER_CONFIGURED'
                else:
                    report = episode_runner(notification_id)
                    decision = decide(report)
                    item['decision'] = decision['decision']
                    item['issues'] = decision.get('issues', [])
                    if decision['series_identity_verified'] and decision.get('tvdb_episode_exists'):
                        result = persist(verified, decision, apply=apply_series)
                        item.update(action=result['action'], anidb_id=result['anidb_id'], tvdb_id=result['tvdb_id'])
                    else:
                        item['action'] = 'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE'
        except Exception as exc:
            item['action'] = 'ERROR_RETRY_NO_STATUS_CHANGE'
            item['error'] = type(exc).__name__ + ': ' + str(exc)
        output['items'].append(item)
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--inbox',type=Path,default=DEFAULT_DATA/'inbox.db')
    p.add_argument('--verified',type=Path,default=DEFAULT_DATA/'verified-series.db')
    p.add_argument('--limit',type=int,default=5)
    p.add_argument('--apply-series',action='store_true',help='Only insert verified series evidence in dedicated DB')
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--lookup-new',action='store_true',help='Perform network identity checks for unpersisted items')
    args=p.parse_args()
    if not 1 <= args.limit <= 100: p.error('--limit must be between 1 and 100')
    runner=None
    if args.lookup_new:
        from anime_identity_episode_v6 import run_v3, audit, inspect, data_path, config_get, tvdb_token, TVDB_URL, request_json
        from urllib.parse import urlencode
        import os
        def runner(notification_id):
            report=run_v3(notification_id)
            if report.get('issues'): return report
            report=audit(report,data_path('anime-lists.xml').read_bytes())
            if report.get('issues') or len(report.get('episode_audit') or [])!=1: return report
            key=(config_get('tvdb.api_key') or '').strip() if config_get('tvdb.enabled') else ''
            if not key: raise ValueError('TVDB unavailable')
            token=tvdb_token(key,os.getenv('ANIME_TVDB_PIN',''))
            return inspect(report,lambda sid,page:request_json(f'{TVDB_URL}/series/{int(sid)}/episodes/default?'+urlencode({'page':page}),bearer=token))
    result=process(args.inbox,args.verified,args.limit,args.apply_series,runner)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'items':len(result['items']),'actions':[x['action'] for x in result['items']]},indent=2))
    return 0 if not any(x['action']=='ERROR_RETRY_NO_STATUS_CHANGE' for x in result['items']) else 2
if __name__=='__main__': raise SystemExit(main())
