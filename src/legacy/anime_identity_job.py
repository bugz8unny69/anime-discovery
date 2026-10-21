"""Job-driven identity resolution, reusing the existing provider verification.

One leased identity_resolution job owns one notification. Notification records
remain durable Series History, while retries belong to daemon_jobs.
"""
import asyncio
import json
import sqlite3

from anime_unified_identity_monitor import check_once


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
