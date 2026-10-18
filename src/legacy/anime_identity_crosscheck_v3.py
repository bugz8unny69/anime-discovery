#!/usr/bin/env python3
"""Read-only TVDB media-type and explicit AniDB remote-ID cross-check.

Never approves identities, updates inbox, or triggers acquisition.
"""
import argparse
import json
from anime_identity_crosscheck import crosscheck
from anime_config_runtime import data_path, get
from anime_identity_verify import TVDB_URL, request_json, tvdb_token


def classify_tvdb(record):
    """Use explicit type/genre metadata; titles never establish media type."""
    labels = []
    for key in ('seriesType', 'type'):
        value = record.get(key)
        if isinstance(value, dict):
            labels.extend(str(value.get(k, '')) for k in ('name', 'slug'))
        elif isinstance(value, str):
            labels.append(value)
    for value in record.get('genres') or []:
        if isinstance(value, dict):
            labels.append(str(value.get('name') or ''))
        elif isinstance(value, str):
            labels.append(value)
    terms = {x.strip().casefold() for x in labels if x and x.strip()}
    animation = any('animation' in x or x == 'anime' for x in terms)
    live = any('live action' in x or 'live-action' in x for x in terms)
    if animation and live:
        return 'CONFLICTING_MEDIA_TYPE', sorted(terms)
    if live:
        return 'LIVE_ACTION', sorted(terms)
    if animation:
        return 'ANIMATION', sorted(terms)
    return 'UNKNOWN', sorted(terms)


def explicit_anidb_ids(record):
    """Accept only an explicitly labeled AniDB remote ID, not a generic URL."""
    ids = set()
    for item in record.get('remoteIds') or []:
        if not isinstance(item, dict):
            continue
        source = item.get('sourceName') or item.get('source') or ''
        if isinstance(source, dict):
            source = source.get('name', '')
        source = str(source).strip().casefold()
        if source != 'anidb':
            continue
        value = str(item.get('id') or '').strip()
        if value.isdecimal():
            ids.add(str(int(value)))
    return sorted(ids)


def decide(pairs, errors):
    if errors:
        return 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
    explicit = [p for p in pairs if p['explicit_anidb_link'] and p['media_type'] == 'ANIMATION']
    conflicts = [p for p in pairs if p['explicit_anidb_conflict']]
    if conflicts or len(explicit) > 1:
        return 'CONFLICTING_REMOTE_LINKS; NEEDS_REVIEW_CANDIDATE'
    if len(explicit) == 1:
        return 'EXPLICIT_LINK_AND_ANIMATION_CORROBORATED; MANUAL_AUDIT_REQUIRED'
    plausible = [p for p in pairs if p['title_corroborated'] and p['media_type'] != 'LIVE_ACTION']
    if len(plausible) == 1:
        return 'SINGLE_PLAUSIBLE_ANIME; CROSS_REFERENCE_REQUIRED'
    if plausible:
        return 'AMBIGUOUS_CANDIDATES; DO_NOT_CHANGE_STATUS'
    return 'NO_ELIGIBLE_MATCH; NEEDS_REVIEW_CANDIDATE'


def run(notification_id):
    report = crosscheck(notification_id, data_path('anidb-titles.xml.gz'))
    report['crosscheck_v3'] = []
    report['verified_identity'] = False
    report['usable_for_automation'] = False
    if report['issues']:
        report['next_action'] = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
        return report
    api_key = get('tvdb.api_key') if get('tvdb.enabled') else None
    if not api_key:
        report['issues'].append('TVDB unavailable')
        report['next_action'] = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
        return report
    try:
        token = tvdb_token(api_key)
    except Exception as exc:
        report['issues'].append('TVDB auth: ' + type(exc).__name__)
        report['next_action'] = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
        return report
    details = {}
    for row in report['tvdb_search_candidates'][:20]:
        tid = str(row['tvdb_id'])
        try:
            data = request_json(f'{TVDB_URL}/series/{int(tid)}/extended', bearer=token).get('data') or {}
            if str(data.get('id')) != tid:
                raise ValueError('TVDB series ID mismatch')
            details[tid] = data
        except Exception as exc:
            report['issues'].append(f'TVDB detail {tid}: {type(exc).__name__}')
    for pair in report['pair_evidence']:
        raw = details.get(str(pair['tvdb_id']))
        if raw is None:
            continue
        media, labels = classify_tvdb(raw)
        ids = explicit_anidb_ids(raw)
        aid = str(pair['anidb_id'])
        report['crosscheck_v3'].append({
            'anidb_id': aid, 'tvdb_id': str(pair['tvdb_id']),
            'title_corroborated': pair['title_corroborated'],
            'media_type': media, 'media_labels': labels,
            'tvdb_explicit_anidb_ids': ids,
            'explicit_anidb_link': aid in ids,
            'explicit_anidb_conflict': bool(ids) and aid not in ids,
        })
    report['next_action'] = decide(report['crosscheck_v3'], report['issues'])
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--notification-id', type=int, default=1)
    args = p.parse_args()
    try:
        print(json.dumps(run(args.notification_id), ensure_ascii=False, indent=2))
    except Exception as exc:
        p.exit(2, f'Crosscheck v3 unavailable: {type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
