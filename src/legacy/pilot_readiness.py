"""Read-only production readiness audit and disposable SQLite restore rehearsal.

No qB or Sonarr mutation methods. No controller import or service modification.
"""
import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path

from production_edges import snapshot_to_disposable, EdgeBlocked


class ReadinessBlocked(RuntimeError):
    pass


def rehearse_restore(source, *, workdir=None):
    """Backup and restore into two exclusive, temporary SQLite paths.

    Neither copy is allowed inside the production database directory. Uses
    SQLite backup API in both directions; validates integrity and row counts.
    """
    with tempfile.TemporaryDirectory(prefix='anime-restore-', dir=workdir) as td:
        first = Path(td) / 'snapshot.db'
        restored = Path(td) / 'restored.db'
        snapshot_to_disposable(source, first)
        snapshot_to_disposable(first, restored)
        with sqlite3.connect(first) as a, sqlite3.connect(restored) as b:
            def inventory(db):
                tables = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
                counts = {}
                for table in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    counts[table] = db.execute('SELECT COUNT(*) FROM ' + quoted).fetchone()[0]
                return counts
            original_counts, restored_counts = inventory(a), inventory(b)
            if original_counts != restored_counts:
                raise ReadinessBlocked('restored table counts differ')
            if b.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ReadinessBlocked('restored database failed integrity check')
            if b.execute('PRAGMA foreign_key_check').fetchall():
                raise ReadinessBlocked('restored database failed foreign key check')
            return {'restore_rehearsal': 'PASS', 'table_counts': restored_counts,
                    'production_database_modified': False}


def audit_series_mapping(series, episodes):
    """Assess Sonarr numbering *without* granting mapping approval.

    No title-based auto-match. Reject specials, missing IDs, duplicate or
    non-contiguous season-one episode numbers. Sonarr alone is not independent
    metadata evidence and cannot authorize Keep or import.
    """
    if not isinstance(series, dict) or type(series.get('id')) is not int or series['id'] <= 0:
        raise ReadinessBlocked('invalid Sonarr series identity')
    tvdb = series.get('tvdbId')
    if type(tvdb) is not int or tvdb <= 0:
        raise ReadinessBlocked('missing Sonarr TVDB identity')
    if not isinstance(episodes, list):
        raise ReadinessBlocked('invalid Sonarr episode response')
    season_one = []
    for ep in episodes:
        if not isinstance(ep, dict):
            raise ReadinessBlocked('invalid Sonarr episode record')
        if ep.get('seasonNumber') == 1:
            number = ep.get('episodeNumber')
            if type(number) is not int or number <= 0:
                raise ReadinessBlocked('invalid season-one episode number')
            season_one.append(number)
    if len(set(season_one)) != len(season_one):
        raise ReadinessBlocked('duplicate Sonarr season-one episode numbers')
    prefix = []
    for n in range(1, 7):
        if n in season_one:
            prefix.append(n)
        else:
            break
    if not prefix:
        raise ReadinessBlocked('Sonarr season one lacks episode 1')
    return {'sonarr_series_id': series['id'], 'tvdb_id': tvdb,
            'season_one_episode_count': len(season_one), 'contiguous_trial_prefix': prefix,
            'canonical_mapping_approved': False, 'independent_evidence_required': True}


def audit_sonarr(client, *, series_id):
    if type(series_id) is not int or series_id <= 0:
        raise ReadinessBlocked('explicit positive Sonarr series ID required')
    # Explicit ID only; never fuzzy-match titles or write series IDs to controller.
    series = [s for s in client.series() if type(s.get('id')) is int and s['id'] == series_id]
    if len(series) != 1:
        raise ReadinessBlocked('Sonarr series ID not found or ambiguous')
    return audit_series_mapping(series[0], client.episodes(series_id))


def main():
    parser = argparse.ArgumentParser(description='Read-only readiness audit; no external writes')
    parser.add_argument('--restore-rehearsal', action='store_true')
    parser.add_argument('--db', default='/var/lib/anime-discovery/controller.db')
    parser.add_argument('--sonarr-series-id', type=int)
    args = parser.parse_args()
    if not args.restore_rehearsal and args.sonarr_series_id is None:
        parser.error('select --restore-rehearsal and/or --sonarr-series-id')
    report = {}
    if args.restore_rehearsal:
        report['database'] = rehearse_restore(args.db)
    if args.sonarr_series_id is not None:
        from anime_service_adapters import SonarrReadOnly
        key = os.environ.get('SONARR_API_KEY')
        if not key:
            raise ReadinessBlocked('SONARR_API_KEY must be configured locally')
        client = SonarrReadOnly('https://sonarr.arr.internal', key)
        report['sonarr'] = audit_sonarr(client, series_id=args.sonarr_series_id)
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == '__main__':
    main()
