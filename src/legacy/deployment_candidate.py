"""Offline deployment-candidate preflight. No production writes or qBittorrent mutations."""
import os
import sqlite3
from pathlib import Path
from trial_integration_sprint import assert_disposable

REQUIRED = {'series','episodes','download_attempts','staged_episodes','file_observations',
            'trial_mapping_gate','trial_decision_gate','trial_cancel_outbox'}


def audit(db_path):
    path = assert_disposable(db_path)
    uri = Path(path).as_uri() + '?mode=ro'
    with sqlite3.connect(uri, uri=True) as db:
        db.execute('PRAGMA foreign_keys=ON')
        tables = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        missing = sorted(REQUIRED-tables)
        integrity = db.execute('PRAGMA integrity_check').fetchone()[0]
        foreign_keys = db.execute('PRAGMA foreign_key_check').fetchall()
        pending = db.execute("SELECT COUNT(*) FROM trial_cancel_outbox WHERE status='PENDING'").fetchone()[0] if not missing else None
        return {'ready_for_offline_rehearsal': not missing and integrity=='ok' and not foreign_keys,
                'ready_for_production': False, 'missing_tables':missing,
                'integrity':integrity, 'foreign_key_violations':len(foreign_keys),
                'pending_cancellation_jobs':pending,
                'blockers':['PROVENANCE_ADAPTER_UNVERIFIED','FILE_IDENTITY_RACE_NOT_CLOSED',
                            'QBITTORRENT_MUTATION_WORKER_NOT_DEPLOYED',
                            'PRODUCTION_SNAPSHOT_RESTORE_NOT_VERIFIED']}


def snapshot_disposable(source, destination):
    """SQLite-consistent snapshot of an explicit disposable DB, never live DB."""
    source = assert_disposable(source)
    dest = Path(destination)
    if dest.exists() or dest.is_symlink() or dest.resolve() == Path(source).resolve():
        raise ValueError('Snapshot destination must be a new, distinct path')
    if dest.parent.resolve() == Path('/var/lib/anime-discovery'):
        raise ValueError('Production directory forbidden')
    try:
        with sqlite3.connect(Path(source).as_uri()+'?mode=ro',uri=True) as src:
            with sqlite3.connect(str(dest)) as out:
                src.backup(out)
                if out.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                    raise RuntimeError('Snapshot integrity failure')
        return str(dest)
    except BaseException:
        dest.unlink(missing_ok=True)
        raise


def cancellation_plan(db_path, inventory):
    """Fail-closed read-only plan; never makes a qBittorrent API request."""
    from qb_inventory_adapter import InventoryItem
    path = assert_disposable(db_path)
    if not isinstance(inventory,(tuple,list)) or any(not isinstance(i,InventoryItem) for i in inventory):
        raise ValueError('Trusted inventory records required')
    counts={}
    for item in inventory:
        key=item.torrent_hash.lower()
        counts[key]=counts.get(key,0)+1
    indexed={i.torrent_hash.lower():i for i in inventory}
    with sqlite3.connect(Path(path).as_uri()+'?mode=ro',uri=True) as db:
        db.row_factory=sqlite3.Row
        jobs=db.execute('''SELECT o.id,o.series_id,o.attempt_id,o.torrent_hash,o.delete_files,
              a.torrent_hash AS current_hash,a.status AS attempt_status,a.series_id AS attempt_series,
              d.action AS decision_action
              FROM trial_cancel_outbox o
              LEFT JOIN download_attempts a ON a.id=o.attempt_id
              LEFT JOIN trial_decision_gate d ON d.series_id=o.series_id
              WHERE o.status='PENDING' ORDER BY o.id''').fetchall()
        results=[]
        for job in jobs:
            h=job['torrent_hash'].lower()
            valid=(job['delete_files']==0 and job['attempt_series']==job['series_id']
                   and job['current_hash'] is not None and job['current_hash'].lower()==h
                   and job['attempt_status'] in ('QUEUED','DOWNLOADING','STALLED')
                   and job['decision_action'] in ('KEEP','REJECT') and counts.get(h,0)==1)
            results.append({'job_id':job['id'],'attempt_id':job['attempt_id'],
                'outcome': 'WOULD_REMOVE_WITH_DELETE_FILES_FALSE' if valid else 'BLOCKED',
                'present':h in indexed,'dry_run':True})
        return results
