"""Opt-in acquisition handler; never registered by default."""
import asyncio
import json
import sqlite3
import time
from anime_claimed_pipeline import process_claimed
from anime_acquisition_finalize import finalize_acquisition
from anime_acquisition_gate import approved_dispatch
from anime_jellyfin_refresh import refresh_best_effort
from anime_trial_metadata import tvdb_english_title
from anime_series_naming import resolve_series_name
from anime_flat_config import load_config


def make_acquisition_handler(db_path, qb_factory, *, download_root, trial_root, cleanup_source=False, jellyfin_refresh=None):
    if not callable(qb_factory):
        raise ValueError('qBittorrent client factory required')

    def execute(job, payload):
        with sqlite3.connect(db_path, isolation_level=None, timeout=10) as db:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('PRAGMA busy_timeout=10000')
            row = db.execute('''SELECT state,lease_token,lease_until
                FROM daemon_jobs WHERE id=? AND kind='claimed_acquisition' ''',
                (job['id'],)).fetchone()
            if (not row or row[0] != 'LEASED' or row[1] != job['lease_token']
                    or row[2] < time.time()):
                raise ValueError('Stale acquisition lease')
            dispatch=db.execute("SELECT state FROM episode_dispatch WHERE notification_id=?",
                                (payload['notification_id'],)).fetchone()
            if dispatch and dispatch[0]=='DONE':
                record=db.execute("SELECT 1 FROM torrent_recovery_records WHERE notification_id=?",
                                  (payload['notification_id'],)).fetchone()
                if not record:
                    return {'state':'NEEDS_REVIEW'}
                return {'state':'DONE'}
            if dispatch and dispatch[0]=='NEEDS_REVIEW':
                return {'state':'NEEDS_REVIEW'}
            # Recheck approval before constructing any external client. A series
            # may have been quarantined or rejected since the job was enqueued.
            approval=approved_dispatch(db, payload['notification_id'])
            # Resolve a clean English series name from verified TVDB identity
            # or a unique recognized mapping BEFORE contacting qBittorrent.
            # Never use the Autobrr release label as a folder name.
            config=None
            try:
                config=load_config()
                key=(config.get('secrets') or {}).get('tvdb_api_key') if config.get('settings',{}).get('tvdb',{}).get('enabled') else None
                english_title=tvdb_english_title(payload['tvdb_id'],key)
            except (OSError,ValueError,KeyError):
                english_title=None
            aliases=(config or {}).get('settings',{}).get('identity',{}).get('series_map',{})
            series_name=resolve_series_name(db,approval['series_id'],payload['tvdb_id'],
                english_title=english_title,series_map=aliases)
            result=process_claimed(db, payload['notification_id'],
                infohash=payload['infohash'], magnet_uri=payload['magnet_uri'],
                qb=qb_factory(), download_root=download_root,
                trial_root=trial_root, title=series_name,
                tvdb_id=payload['tvdb_id'],english_title=series_name)
            if result['state']=='DONE':
                finalize_acquisition(db,job['id'],job['lease_token'],
                    payload['notification_id'],series_title=series_name)
                # Only scan once after durable finalization; never undo staging
                # or retry acquisition because the Jellyfin service is down.
                refresh_best_effort(jellyfin_refresh)
                # qBittorrent sources are intentionally retained until the
                # explicit Sonarr Keep finalization. This is the only stage
                # allowed to clean up proven-owned torrents.
            return result

    async def handler(job):
        try:
            payload = json.loads(job['payload_json'])
            if not isinstance(payload, dict) or set(payload) != {
                    'notification_id', 'infohash', 'magnet_uri', 'title', 'tvdb_id'}:
                return 'NEEDS_REVIEW'
            if (type(payload['notification_id']) is not int or
                    payload['notification_id'] <= 0 or
                    str(payload['notification_id']) != job['subject_key']):
                return 'NEEDS_REVIEW'
            if any(not isinstance(payload[k], str) or not payload[k]
                   for k in ('infohash', 'magnet_uri', 'title')):
                return 'NEEDS_REVIEW'
            if not str(payload['tvdb_id']).isdigit() or int(payload['tvdb_id']) <= 0:
                return 'NEEDS_REVIEW'
        except (KeyError, TypeError, ValueError):
            return 'NEEDS_REVIEW'
        result = await asyncio.to_thread(execute, job, payload)
        return result['state']

    return handler
