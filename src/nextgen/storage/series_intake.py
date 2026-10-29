"""Series-first Intake read model and manual missing-episode search.

Existing per-operation Keep jobs and Prowlarr discovery do all real work.
No new tables, provider adapters, or import jobs are needed.
"""
import json

from src.nextgen.history import integer
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction, enqueue_job_with_receipt
from src.nextgen.storage.sonarr_backfill import PAGE_SIZE, window


class IntakeUnavailable(ValueError):
    reason_code = 'MANAGEMENT_ACTION_UNAVAILABLE'


def detail(db, anidb_id):
    integer(anidb_id, positive=True)
    row = db.execute(
        'SELECT anidb_id,tvdb_series_id,title FROM identified_anime WHERE anidb_id=?',
        (anidb_id,)).fetchone()
    if row is None:
        return None
    info = db.execute(
        'SELECT series_json FROM identity_results WHERE anidb_id=? '
        'ORDER BY validated_at_ms DESC LIMIT 1', (anidb_id,)).fetchone()
    anime = json.loads(info[0]).get('anime', {}) if info else {}
    result = {
        'anidb_id': row[0], 'tvdb_series_id': row[1], 'title': row[2],
        'english_title': anime.get('english_title'), 'original_title': anime.get('original_title'),
        'year': anime.get('year'), 'type': anime.get('type'),
        'description': None,  # The persisted AnimeSeries identity has no synopsis field.
        'episodes': [], 'missing': [], 'keep_operations': []
    }
    # Existing single-episode staging (one underlying operation per release).
    single = db.execute(
        "SELECT r.tvdb_season,r.tvdb_episode,s.job_id,m.operation_id,o.state,"
        " k.job_id,k.state FROM staging_publications s "
        "JOIN acquisition_plans p USING(plan_id) "
        "JOIN episode_reservations r USING(reservation_id) "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "JOIN job_operations o ON o.operation_id=m.operation_id "
        "LEFT JOIN management_actions a ON a.operation_id=m.operation_id AND a.action='KEEP' "
        "LEFT JOIN jobs k ON k.job_id=a.job_id "
        "WHERE r.anidb_id=? AND s.state='PUBLISHED'",
        (anidb_id,)).fetchall()
    # Season-pack episodes use their existing batch Keep operation.
    batch = db.execute(
        "SELECT r.tvdb_season,r.tvdb_episode,s.job_id,m.operation_id,o.state,"
        " k.job_id,k.state FROM batch_staging_publications s "
        "JOIN batch_episode_reservations r ON r.plan_id=s.plan_id AND r.file_index=s.file_index "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "JOIN job_operations o ON o.operation_id=m.operation_id "
        "LEFT JOIN management_actions a ON a.operation_id=m.operation_id AND a.action='KEEP' "
        "LEFT JOIN jobs k ON k.job_id=a.job_id "
        "WHERE r.anidb_id=? AND s.state='PUBLISHED'",
        (anidb_id,)).fetchall()
    operations = set()
    staged_episodes = set()
    for season, episode, job, op, state, keep_job, keep_state in sorted(single + batch):
        status = ('Kept' if keep_state == 'DONE' else
                  'Importing' if keep_job is not None else
                  'Staged' if state == 'STAGED' else state.title())
        result['episodes'].append({
            'season': season, 'episode': episode, 'job_id': job,
            'operation_id': op, 'status': status
        })
        staged_episodes.add((season, episode))
        if state == 'STAGED' and keep_state != 'DONE':
            operations.add(op)
    result['keep_operations'] = sorted(operations)
    plans = db.execute(
        'SELECT plan_id,tvdb_season,anchor_episode,backfill_count,following_count '
        'FROM trial_plans WHERE anidb_id=? ORDER BY tvdb_season', (anidb_id,)
    ).fetchall()
    for plan_id, season, anchor, backfill, following in plans:
        observed = dict(db.execute(
            'SELECT tvdb_episode,status FROM sonarr_backfill_results WHERE plan_id=?',
            (plan_id,)).fetchall())
        for episode in window(anchor, backfill, following):
            if (season, episode) in staged_episodes:
                continue
            status = observed.get(episode, 'NOT_SEARCHED')
            result['missing'].append({
                'season': season, 'episode': episode, 'status': status,
                'can_retry': status in ('NOT_SEARCHED', 'NO_RESULTS', 'NOT_AIRED', 'MAPPING_MISSING')
            })
    return result


def list_items(db, before, limit):
    rows = db.execute(
        'SELECT anidb_id FROM identified_anime WHERE anidb_id<? '
        'ORDER BY anidb_id DESC LIMIT ?', (before, limit + 1)
    ).fetchall()
    items = []
    for (aid,) in rows[:limit]:
        item = detail(db, aid)
        items.append({
            'anidb_id': aid, 'title': item['title'],
            'tvdb_series_id': item['tvdb_series_id'],
            'staged_count': sum(x['status'] == 'Staged' for x in item['episodes']),
            'kept_count': sum(x['status'] == 'Kept' for x in item['episodes']),
            'missing_count': sum(x['can_retry'] for x in item['missing']),
            'season_count': len({x['season'] for x in item['episodes'] + item['missing']})
        })
    return {'items': items, 'next_before_id': rows[limit - 1][0] if len(rows) > limit else None}


def keep_targets(db, anidb_id, operation_ids):
    info = detail(db, anidb_id)
    if info is None or type(operation_ids) is not list or not 1 <= len(operation_ids) <= 100:
        raise IntakeUnavailable()
    if any(type(x) is not int or x <= 0 for x in operation_ids):
        raise IntakeUnavailable()
    wanted = set(operation_ids)
    if len(wanted) != len(operation_ids) or not wanted.issubset(set(info['keep_operations'])):
        raise IntakeUnavailable()
    # Resolve each captured operation to an existing staged job. A new arrival
    # cannot silently become part of the approved Keep scope.
    rows = db.execute(
        'SELECT m.operation_id,MAX(m.job_id) FROM job_operation_members m '
        'WHERE m.operation_id IN (' + ','.join('?' for _ in wanted) + ') '
        'GROUP BY m.operation_id', tuple(sorted(wanted))
    ).fetchall()
    if len(rows) != len(wanted):
        raise IntakeUnavailable()
    return [job for op, job in sorted(rows)]


def retry_episode(database, anidb_id, season, episode):
    integer(anidb_id, positive=True)
    integer(season)
    integer(episode, positive=True)
    if season < 0:
        raise IntakeUnavailable()
    queue = JobQueue(database)
    with queue.connection() as db, transaction(db):
        row = db.execute(
            "SELECT p.plan_id,p.anchor_episode,p.backfill_count,p.following_count,"
            " j.event_id,j.job_id FROM trial_plans p "
            "JOIN release_verifications v ON v.verification_id=p.anchor_verification_id "
            "JOIN jobs j ON j.job_id=v.job_id "
            "WHERE p.anidb_id=? AND p.tvdb_season=?",
            (anidb_id, season)).fetchone()
        if row is None:
            raise IntakeUnavailable()
        plan_id, anchor, backfill, following, event_id, parent_job = row
        numbers = window(anchor, backfill, following)
        if episode not in numbers:
            raise IntakeUnavailable()
        prior = db.execute(
            'SELECT status FROM sonarr_backfill_results WHERE plan_id=? AND tvdb_episode=?',
            (plan_id, episode)).fetchone()
        if prior and prior[0] not in ('NO_RESULTS', 'NOT_AIRED', 'MAPPING_MISSING'):
            raise IntakeUnavailable()
        for table in ('episode_reservations', 'batch_episode_reservations'):
            if db.execute(
                f"SELECT 1 FROM {table} WHERE anidb_id=? AND tvdb_season=? "
                "AND tvdb_episode=? AND state='ACTIVE' LIMIT 1",
                (anidb_id, season, episode)).fetchone():
                raise IntakeUnavailable()
        pending = db.execute(
            "SELECT job_id FROM jobs WHERE kind='DISCOVER_SONARR_BACKFILL' "
            "AND state IN ('PENDING','RUNNING','RETRY_WAIT') "
            "AND json_extract(payload_json,'$.plan_id')=? "
            "AND (json_extract(payload_json,'$.retry_episode')=? "
            "OR json_extract(payload_json,'$.retry_episode') IS NULL) LIMIT 1",
            (plan_id, episode)).fetchone()
        if pending:
            return {'job_id': pending[0], 'reused': True}
        start = (numbers.index(episode) // PAGE_SIZE) * PAGE_SIZE + 1
        job, _ = enqueue_job_with_receipt(
            db, kind='DISCOVER_SONARR_BACKFILL',
            payload={'plan_id': plan_id, 'start': start, 'retry_episode': episode},
            event_id=event_id, created_by_job_id=parent_job, component='api'
        )
        return {'job_id': job, 'reused': False}
