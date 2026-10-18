#!/usr/bin/env python3
"""Read-only TVDB episode existence probe. Never infers a missing AniDB episode offset."""
import argparse
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from anime_config_runtime import get as config_get
from anime_identity_verify import TVDB_URL, request_json, tvdb_token
from anime_identity_audit_v5 import audit, write_json_atomic
from anime_identity_crosscheck_v3 import run as run_v3
from anime_config_runtime import data_path


def extract_episodes(payload):
    data = payload.get('data') or {}
    if isinstance(data, dict):
        episodes = data.get('episodes') or []
    elif isinstance(data, list):
        episodes = data
    else:
        raise ValueError('Unexpected TVDB episodes response')
    if not isinstance(episodes, list):
        raise ValueError('Unexpected TVDB episodes list')
    return episodes


def inspect(report, fetch):
    report['tvdb_episode_checks'] = []
    report['verified_identity'] = False
    report['usable_for_automation'] = False
    rows = report.get('episode_audit') or []
    if report.get('issues') or len(rows) != 1:
        report['next_action'] = 'RETRY_OR_REVIEW_MAPPING; NO_STATUS_CHANGE'
        return report
    row = rows[0]
    if not row.get('series_mapping_corroborated'):
        report['next_action'] = 'REVIEW_SERIES_MAPPING; NO_STATUS_CHANGE'
        return report
    season, episode = row.get('default_tvdb_season'), row.get('episode_candidate')
    if not isinstance(episode, int) or episode < 1 or not str(season).isdecimal():
        report['next_action'] = 'REVIEW_EPISODE_NUMBER; NO_STATUS_CHANGE'
        return report
    # Query the aired-order season as a corroboration check, NOT as proof of AniDB episode arithmetic.
    tid = row['tvdb_id']
    seen = []
    page = 0
    try:
        while page < 20:
            payload = fetch(tid, page)
            items = extract_episodes(payload)
            seen.extend(x for x in items if isinstance(x, dict))
            links = payload.get('links') or {}
            nxt = links.get('next') if isinstance(links, dict) else None
            if not nxt:
                break
            page += 1
        else:
            raise ValueError('TVDB pagination exceeds 20 pages')
        matching = [x for x in seen if str(x.get('seasonNumber')) == str(season) and x.get('number') == episode]
        check = {'tvdb_id':tid, 'season':int(season), 'candidate_episode':episode,
                 'tvdb_episode_exists_at_same_number':bool(matching),
                 'tvdb_episode_records':[{'id':x.get('id'),'name':x.get('name'), 'aired':x.get('aired'), 'seasonNumber':x.get('seasonNumber'),'number':x.get('number')} for x in matching],
                 'mapping_offset_explicit':row.get('episode_offset') is not None,
                 'anidb_episode_mapping_verified':False,
                 'pages_fetched':page+1}
        report['tvdb_episode_checks'].append(check)
        if not matching:
            report['next_action'] = 'TVDB_EPISODE_NOT_FOUND; REVIEW_OR_RETRY; NO_STATUS_CHANGE'
        elif row.get('episode_offset') is None or row.get('episode_specific_rules'):
            report['next_action'] = 'TVDB_EPISODE_EXISTS; ANIDB_EPISODE_RULE_UNRESOLVED; NO_STATUS_CHANGE'
        else:
            report['next_action'] = 'TVDB_EPISODE_EXISTS; FINAL_EPISODE_MAPPING_AUDIT_REQUIRED; NO_STATUS_CHANGE'
    except Exception as exc:
        report.setdefault('issues', []).append(f'TVDB episode lookup failed: {type(exc).__name__}: {exc}')
        report['next_action'] = 'RETRY_TVDB_EPISODES; NO_STATUS_CHANGE'
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--notification-id', type=int, default=1)
    p.add_argument('--mapping-file', type=Path)
    p.add_argument('--output', type=Path, required=True)
    args = p.parse_args()
    try:
        base = run_v3(args.notification_id)
        if base.get('issues'):
            report = base
            report['next_action'] = 'RETRY_LOOKUP; NO_STATUS_CHANGE'
        else:
            report = audit(base, (args.mapping_file or data_path('anime-lists.xml')).read_bytes())
            if len(report.get('episode_audit') or []) == 1:
                key = (config_get('tvdb.api_key') or '').strip() if config_get('tvdb.enabled') else ''
                if not key:
                    raise ValueError('TVDB API key unavailable')
                token = tvdb_token(key, os.getenv('ANIME_TVDB_PIN', ''))
                def fetch(series_id, page):
                    url = f'{TVDB_URL}/series/{int(series_id)}/episodes/default?' + urlencode({'page':page})
                    return request_json(url, bearer=token)
                report = inspect(report, fetch)
        report['audit_version'] = 6
        report['generated_utc'] = datetime.now(timezone.utc).isoformat()
    except Exception as exc:
        report = {'audit_version':6,'notification_id':args.notification_id,
                  'issues':[f'{type(exc).__name__}: {exc}'], 'verified_identity':False,
                  'usable_for_automation':False, 'next_action':'RETRY_EPISODE_CHECK; NO_STATUS_CHANGE'}
    write_json_atomic(args.output, report)
    print(f'Wrote {args.output}; next_action={report["next_action"]}')
    return 2 if report.get('issues') else 0

if __name__ == '__main__':
    raise SystemExit(main())
