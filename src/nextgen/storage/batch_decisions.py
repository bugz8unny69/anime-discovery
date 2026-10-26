"""Read-only complete batch publication scope for Keep/Reject decisions."""
import json

from src.nextgen.staging import StagingReview
from src.nextgen.storage.cancellation import operation


def batch_staged(db,operation_id):
    row=db.execute(
        "SELECT state FROM job_operations WHERE operation_id=?",
        (operation_id,)).fetchone()
    if row!=('STAGED',):raise StagingReview()
    rows=db.execute(
        "SELECT s.plan_id,s.file_index,s.tvdb_episode,s.manifest_json,"
        "s.receipts_json,b.anidb_id "
        "FROM batch_staging_publications s "
        "JOIN batch_trial_plans p ON p.plan_id=s.plan_id "
        "JOIN batch_verifications b ON b.batch_id=p.batch_id "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "WHERE m.operation_id=? AND s.state='PUBLISHED' "
        "ORDER BY s.tvdb_episode,s.file_index",
        (operation_id,)).fetchall()
    if not rows or len(rows)>1000:raise StagingReview()
    plans={r[0] for r in rows}
    aids={r[5] for r in rows}
    if len(plans)!=1 or len(aids)!=1:raise StagingReview()
    plan_id=rows[0][0]
    expected=db.execute(
        "SELECT count(*) FROM batch_trial_files WHERE plan_id=?",
        (plan_id,)).fetchone()[0]
    if expected!=len(rows):raise StagingReview()
    indices=set()
    episodes=set()
    results=[]
    for plan,index,episode,manifest,receipts,aid in rows:
        if index in indices or episode in episodes:raise StagingReview()
        indices.add(index);episodes.add(episode)
        try:
            doc=json.loads(manifest)
            proofs=json.loads(receipts)
            if (type(doc) is not dict or doc.get('transfer')!='COPY'
                    or type(proofs) is not list or len(proofs)!=3
                    or [e.get('role') for e in doc['entries']]!=
                       [p.get('role') for p in proofs]
                    or set(p['role'] for p in proofs)!={'media','episode','series'}):
                raise StagingReview()
        except (KeyError,TypeError,ValueError):
            raise StagingReview() from None
        results.append((aid,plan,index,episode,manifest,receipts))
    return tuple(results)


def batch_operation(db,job_id):
    op=operation(db,job_id)
    try:
        publications=batch_staged(db,op[0])
    except StagingReview:
        return None
    return publications
