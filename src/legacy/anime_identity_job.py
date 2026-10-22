"""Job-driven identity resolution, reusing the existing provider verification.

One leased identity_resolution job owns one notification. Notification records
remain durable Series History, while retries belong to daemon_jobs.
"""
import asyncio
import json
import sqlite3

from anime_unified_identity_monitor import check_once
from anime_hook_chain import HookRegistry
from anime_trace_history import record, for_notification


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
                trace_id=for_notification(nid)
                context={"db":db,"settings":settings,"secrets":secrets,"nid":nid}
                hooks=HookRegistry()

                def verify(context):
                    context["result"]=check_once(context["db"],context["settings"],
                                                 context["secrets"],notification_id=context["nid"])
                    return "CONTINUE"

                def classify(context):
                    status=db.execute("SELECT status FROM notifications WHERE id=?",
                                      (nid,)).fetchone()
                    if status is None:
                        return "REVIEW"
                    if context["result"]["pending_retries"] or status[0]=="IDENTIFYING":
                        return "RETRY"
                    if status[0]=="NEEDS_REVIEW":
                        return "REVIEW"
                    return "CONTINUE"

                hooks.register("identity","verify_identity",verify)
                hooks.register("identity","classify_result",classify)
                def journal(name,stage,hook,outcome):
                    record(db,trace_id,name,job_id=job["id"],notification_id=nid,
                           stage=stage,hook=hook,outcome=outcome)
                journal("JOB_TRACE_STARTED","identity",None,None)
                try:
                    outcome=hooks.run("identity",context,on_event=journal)
                except Exception:
                    journal("JOB_TRACE_FAILED","identity",None,"RETRY")
                    raise
                result={"CONTINUE":"DONE","STOP":"DONE",
                        "RETRY":"DEFERRED","REVIEW":"NEEDS_REVIEW"}[outcome]
                journal("JOB_TRACE_FINISHED","identity",None,result)
                return result
        return await asyncio.to_thread(run)
    return handle
