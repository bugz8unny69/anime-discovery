#!/usr/bin/env python3
"""Read-only detailed crosscheck of AniDB/TVDB discovery candidates.

Title corroboration is NOT proof of an AniDB↔TVDB cross-reference.
No writes, status transitions, notifications or downloads.
"""
import argparse
import json
import sqlite3
from pathlib import Path

from anime_config_runtime import data_path, get
from anime_identity_verify import tvdb_token, tvdb_series
from anime_identification_probe import release_title, anidb_matches, tvdb_candidates, norm


def assess(anidb_rows, tvdb_rows, details, errors):
    evidence = []
    for a in anidb_rows:
        a_titles = {norm(t) for t in a['titles'] if norm(t)}
        for t in tvdb_rows:
            ident = t['tvdb_id']
            detail = details.get(ident)
            if not detail:
                continue
            overlapping = sorted(a_titles & {norm(x) for x in detail['titles'] if norm(x)})
            evidence.append({
                'anidb_id': a['anidb_id'], 'tvdb_id': ident,
                'tvdb_name': t['name'], 'tvdb_year': detail.get('year', ''),
                'tvdb_titles': detail['titles'],
                'normalized_title_overlap': overlapping,
                'title_corroborated': bool(overlapping),
                'cross_database_link_verified': False,
            })
    corroborated = [r for r in evidence if r['title_corroborated']]
    if errors:
        next_action = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
    elif not anidb_rows or not corroborated:
        next_action = 'NEEDS_REVIEW_CANDIDATE; DO_NOT_CHANGE_STATUS'
    elif len(anidb_rows) != 1 or len(corroborated) != 1:
        next_action = 'AMBIGUOUS_TITLE_MATCH; DO_NOT_CHANGE_STATUS'
    else:
        next_action = 'SINGLE_TITLE_CORROBORATION; CROSS_REFERENCE_REQUIRED'
    return evidence, next_action


def crosscheck(notification_id, cache):
    with sqlite3.connect(f'file:{data_path("inbox.db")}?mode=ro', uri=True) as db:
        row = db.execute('SELECT release_name,status FROM notifications WHERE id=?', (notification_id,)).fetchone()
    if row is None:
        raise ValueError('Notification not found')
    aliases, episode = release_title(row[0])
    result = {'notification_id': notification_id, 'release_name': row[0], 'status_unchanged': row[1],
              'title_candidates': aliases, 'episode_candidate': episode, 'anidb_candidates': [],
              'tvdb_search_candidates': [], 'pair_evidence': [], 'issues': [],
              'verified_identity': False, 'usable_for_automation': False}
    if not cache.is_file():
        result['issues'].append('AniDB title cache missing; run existing probe --refresh-titles')
        result['next_action'] = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
        return result
    result['anidb_candidates'], truncated = anidb_matches(cache, aliases, limit=10)
    if truncated:
        result['issues'].append('AniDB matches truncated; ambiguous result')
    key = get('tvdb.api_key') if get('tvdb.enabled') else None
    if not key:
        result['issues'].append('TVDB disabled or API key unavailable')
        result['next_action'] = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
        return result
    try:
        result['tvdb_search_candidates'], search_errors = tvdb_candidates(aliases, key)
        result['issues'].extend(search_errors)
        token = tvdb_token(key)
    except Exception as exc:
        result['issues'].append(f'TVDB lookup failed: {type(exc).__name__}')
        result['next_action'] = 'RETRY_LOOKUP; DO_NOT_CHANGE_STATUS'
        return result
    details = {}
    for candidate in result['tvdb_search_candidates'][:20]:
        ident = candidate['tvdb_id']
        try:
            details[ident] = tvdb_series(ident, token)
        except Exception as exc:
            result['issues'].append(f'TVDB extended lookup {ident} failed: {type(exc).__name__}')
    evidence, action = assess(result['anidb_candidates'], result['tvdb_search_candidates'], details, result['issues'])
    result['pair_evidence'] = evidence
    result['next_action'] = action
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--notification-id', type=int, default=1)
    p.add_argument('--titles-cache', type=Path, default=None)
    args = p.parse_args()
    try:
        print(json.dumps(crosscheck(args.notification_id, args.titles_cache or data_path('anidb-titles.xml.gz')),
                         indent=2, ensure_ascii=False))
    except Exception as exc:
        p.exit(2, f'Crosscheck unavailable: {type(exc).__name__}: {exc}\n')


if __name__ == '__main__':
    main()
