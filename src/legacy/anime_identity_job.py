"""Job-driven identity resolution, reusing the existing provider verification.

One leased identity_resolution job owns one notification. Notification records
remain durable Series History, while retries belong to daemon_jobs.
"""
import asyncio
import json
import sqlite3

from anime_job_lineage import enqueue_linked
from anime_unified_identity_monitor import check_once


def recover_pending(db_path):
    """Idempotently convert pre-migration pending notifications into jobs.

    The old identity polling process must not run alongside this worker.
    """
    with sqlite3.connect(db_path, isolation_level=None, timeout=10) as db:
        db.execute("PRAGMA busy_timeout=10000")
        rows = db.execute("""SELECT n.id FROM notifications n
            WHERE n.status IN ('UNTRUSTED','RECEIVED','IDENTIFYING')
              AND NOT EXISTS(SELECT 1 FROM episode_dispatch d
                             WHERE d.notification_id=n.id)
            ORDER BY n.id""").fetchall()
        for (nid,) in rows:
            db.execute("""UPDATE notifications SET status='IDENTIFYING'
                WHERE id=? AND status IN ('UNTRUSTED','RECEIVED')""", (nid,))
            enqueue_linked(db, "identity_resolution", "notification:"+str(nid),
                           json.dumps({"notification_id":nid},sort_keys=True),
                           notification_id=nid)


def handler_factory(db_path, settings_supplier):
    async def handle(job):
        try:
            payload=json.loads(job["payload_json"])
            if set(payload) != {"notification_id"}:
                return "NEEDS_REVIEW"
            nid=payload["notification_id"]
            if type(nid) is not int or nid<=0:
                return "NEEDS_REVIEW"
        except (TypeError, ValueError, KeyError):
            return "NEEDS_REVIEW"

        def run():
            settings,secrets=settings_supplier(job)
            with sqlite3.connect(db_path, isolation_level=None, timeout=10) as db:
                db.execute("PRAGMA busy_timeout=10000")
                result=check_once(db,settings,secrets,notification_id=nid)
                status=db.execute("SELECT status FROM notifications WHERE id=?",
                                  (nid,)).fetchone()
                if status is None:
                    return "NEEDS_REVIEW"
                if result["pending_retries"]:
                    return "DEFERRED"
                if status[0] == "NEEDS_REVIEW":
                    return "NEEDS_REVIEW"
                if status[0] == "IDENTIFYING":
                    return "DEFERRED"
                return "DONE"
        return await asyncio.to_thread(run)
    return handle
