"""`adm report job <id>`: one read-only, plain-text report of everything about a job.

Reads the database in read-only mode; never changes state or calls a service.
Covers the job, the work it controls (or is controlled by), every job in that
operation, their full history including which check failed, and every
recorded download/staging path with whether it still exists on disk.
"""
import json
import linecache
import os
import sqlite3
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# (table, column holding a job id, label). Only tables that exist are read.
JOB_TABLES = (
    ('acquisition_plans', 'job_id', 'Acquisition plan'),
    ('episode_reservations', 'owner_job_id', 'Episode reservation'),
    ('sonarr_magnet_intents', 'job_id', 'Magnet intake'),
    ('batch_metadata_admissions', 'verification_job_id', 'Batch metadata admission'),
    ('batch_episode_reservations', 'owner_job_id', 'Batch episode reservation'),
    ('staging_publications', 'job_id', 'Staging publication'),
    ('batch_staging_publications', 'job_id', 'Batch staging publication'),
    ('staging_cleanup_artifacts', 'job_id', 'Staging cleanup artifact'),
)
# Tables keyed by plan_id, reached from the plans above.
PLAN_TABLES = (
    ('torrent_submissions', 'acquisition_plans', 'Torrent submission'),
    ('cancellation_cleanup', 'acquisition_plans', 'Cancellation cleanup journal'),
    ('batch_torrent_submissions', 'batch_episode_reservations', 'Batch torrent submission'),
    ('batch_cancellation_cleanup', 'batch_episode_reservations', 'Batch cancellation cleanup journal'),
)
SKIP = {'files_json', 'manifest_json', 'inventory_json'}  # Large; paths are pulled out below.


def when(ms):
    return '-' if ms is None else datetime.fromtimestamp(ms / 1000).strftime('%Y-%m-%d %H:%M:%S')


def tables(db):
    return {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}


def rows(db, sql, args=()):
    cursor = db.execute(sql, args)
    names = [c[0] for c in cursor.description]
    return [dict(zip(names, row)) for row in cursor.fetchall()]


def paths_in(value, found):
    """Collect absolute paths from a value or JSON text, in order, no repeats."""
    if type(value) is str:
        if value.startswith('/') and '\n' not in value:
            if value not in found: found.append(value)
            return
        if value[:1] in '{[':
            try: value = json.loads(value)
            except ValueError: return
            paths_in(value, found)
    elif type(value) is dict:
        for item in value.values(): paths_in(item, found)
    elif type(value) is list:
        for item in value: paths_in(item, found)


def source(check):
    """The code around a failed check, read from this installed release."""
    try:
        location = check.split(' ')[0]
        file, line = location.rsplit(':', 1); line = int(line)
    except ValueError:
        return []
    out = []
    for number in range(max(1, line - 4), line + 2):
        text = linecache.getline(str(ROOT / file), number).rstrip()
        if text: out.append(('>> ' if number == line else '   ') + f'{number:5} {text}')
    return out


def reason_text(code):
    if code is None: return ''
    from src.nextgen.reasons import get_reason
    reason = get_reason(code)
    return code if reason is None else f'{code} — {reason.message}'


def report(db, job_id, out=print):
    from src.nextgen.reasons import get_reason
    have = tables(db)
    job = rows(db, 'SELECT * FROM jobs WHERE job_id=?', (job_id,))
    if not job:
        out(f'Job #{job_id} does not exist.'); return 1
    job = job[0]
    out(f'=== Job #{job_id} · {job["kind"]} · {job["state"]} · attempt {job["attempt_count"]}')
    out(f'Created {when(job["created_at_ms"])} · updated {when(job["updated_at_ms"])}'
        + (f' · created by Job #{job["created_by_job_id"]}' if job['created_by_job_id'] else ''))
    if job['last_reason_code']:
        out('Reason: ' + reason_text(job['last_reason_code']))
        reason = get_reason(job['last_reason_code'])
        if reason: out('Advice: ' + reason.action)
    event = rows(db, 'SELECT received_at_ms,raw_body FROM incoming_events WHERE event_id=?',
                 (job['event_id'],)) if job['event_id'] else []
    if event:
        try: release = json.loads(event[0]['raw_body'] or b'{}').get('release_name')
        except (ValueError, TypeError, AttributeError): release = None
        out(f'Release: {release or "(not recorded)"} · trace AD-{job["event_id"]} · received {when(event[0]["received_at_ms"])}')
    out('Payload: ' + job['payload_json'])

    # The work this job controls, and the controls acting on this job's work.
    target = rows(db, 'SELECT action,target_job_id FROM management_actions WHERE job_id=?', (job_id,))
    focus = target[0]['target_job_id'] if target else job_id
    if target:
        out(f'This is the {target[0]["action"]} action for Job #{focus}; the report below covers that work.')
    op = rows(db, 'SELECT o.* FROM job_operations o JOIN job_operation_members m USING(operation_id) '
                  'WHERE m.job_id=?', (focus,))
    members = [focus]
    if op:
        op = op[0]
        out(f'\n=== Operation #{op["operation_id"]}: {op["state"]} · cleanup {op["cleanup_state"]}'
            + (f' · {reason_text(op["reason_code"])}' if op['reason_code'] else ''))
        member_rows = rows(db, 'SELECT j.job_id,j.kind,j.state,j.last_reason_code FROM jobs j '
                               'JOIN job_operation_members m USING(job_id) WHERE m.operation_id=? '
                               'ORDER BY j.job_id', (op['operation_id'],))
        members = [m['job_id'] for m in member_rows]
        for m in member_rows:
            out(f'  Job #{m["job_id"]:<6} {m["kind"]:<28} {m["state"]:<12} {m["last_reason_code"] or ""}')
        for action in rows(db, 'SELECT a.action,a.job_id,j.state,j.last_reason_code FROM management_actions a '
                               'JOIN jobs j USING(job_id) WHERE a.operation_id=?', (op['operation_id'],)):
            out(f'  {action["action"]} action: Job #{action["job_id"]} {action["state"]} {action["last_reason_code"] or ""}')

    # History of this job, its target and every member, oldest first.
    scope = sorted({job_id, focus, *members})
    marks = ','.join('?' * len(scope))
    history = rows(db, f'SELECT * FROM job_history WHERE job_id IN ({marks}) ORDER BY occurred_at_ms,history_id', scope)
    out(f'\n=== History ({len(history)} events)')
    failed = []; failed_paths = []
    for h in history:
        details = json.loads(h['details_json'] or '{}')
        line = f'{when(h["occurred_at_ms"])} Job #{h["job_id"]:<6} {h["event_code"]}'
        if h['reason_code']: line += ' · ' + reason_text(h['reason_code'])
        if details.get('cause_reason_code'): line += f' (cause {details["cause_reason_code"]})'
        if h['handler_label']: line += f' [{h["handler_label"]}]'
        out(line)
        if details.get('failed_check'):
            out(f'    failed check: {details["failed_check"]}')
            failed.append(details['failed_check'])
        if details.get('failed_path'):
            out(f'    file: {details["failed_path"]}')
            failed_paths.append(details['failed_path'])
    if failed:
        out('\n=== Code of the last failed check')
        for text in source(failed[-1]): out(text)
    elif job['state'] in ('NEEDS_REVIEW', 'BLOCKED'):
        out('\n(No failed check was recorded; this stop happened before check recording existed. '
            'Resume it once with Retry to record which check fails.)')

    # Every recorded record and path for the work, with on-disk existence.
    out('\n=== Records and paths')
    paths = list(dict.fromkeys(failed_paths))
    plans = {'acquisition_plans': set(), 'batch_episode_reservations': set()}
    for table, column, label in JOB_TABLES:
        if table not in have: continue
        for row in rows(db, f'SELECT * FROM {table} WHERE {column} IN ({",".join("?" * len(members))})', members):
            if table in plans and row.get('plan_id') is not None: plans[table].add(row['plan_id'])
            show(out, label, row, paths)
    for table, source_table, label in PLAN_TABLES:
        ids = sorted(plans[source_table])
        if table not in have or not ids: continue
        for row in rows(db, f'SELECT * FROM {table} WHERE plan_id IN ({",".join("?" * len(ids))})', ids):
            show(out, label, row, paths)
    markers = sorted({p for p in paths if Path(p).name.startswith('ad-')})
    out('\n=== Paths on disk')
    if not paths: out('  (none recorded)')
    for p in paths:
        try: state = 'directory' if os.path.isdir(p) else 'file' if os.path.exists(p) else 'MISSING'
        except OSError as exc: state = f'unreadable ({exc.__class__.__name__})'
        out(f'  [{state}] {p}')
    if markers:
        out('\nDownload folders owned by this work: ' + ', '.join(Path(p).name for p in markers))
    return 0


def show(out, label, row, paths):
    found = []
    for key, value in row.items(): paths_in(value, found)
    shown = {k: v for k, v in row.items() if k not in SKIP and v is not None and not str(k).endswith('_ms')}
    out(f'  {label}: ' + ' '.join(f'{k}={v}' for k, v in shown.items()))
    for p in found:
        if p not in paths: paths.append(p)


def connect(config_dir):
    from src.nextgen.configuration import ConfigurationStore
    database = ConfigurationStore(config_dir).read().value('storage.database_path')
    db = sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=5)
    db.execute('PRAGMA query_only=ON')
    return db


def main(argv):
    import argparse
    parser = argparse.ArgumentParser(prog='adm report', description='Read-only report of one job')
    parser.add_argument('what', choices=('job',))
    parser.add_argument('job_id', type=int)
    parser.add_argument('--config-dir', default='/etc/anime-discovery')
    args = parser.parse_args(argv)
    try:
        db = connect(args.config_dir)
    except Exception as exc:  # Explain plainly; the usual cause is permissions.
        parser.exit(2, f'Cannot open the database read-only ({exc.__class__.__name__}: {exc}). '
                       'Run as root or the anime-discovery service account.\n')
    with db:
        return report(db, args.job_id)
