"""Read-only daemon handler: evaluate migration readiness without side effects.

No torrent submission, media deletion, or Shoko mutations. This handler is
safe to register while write-capable integrations remain disabled.
"""
import asyncio
import json
from anime_migration_preflight import preflight

async def migration_preflight_handler(job):
    try:
        payload=json.loads(job["payload_json"])
    except (KeyError,TypeError,ValueError):
        return "NEEDS_REVIEW"
    if not isinstance(payload,dict) or set(payload)!={"database_path"}:
        return "NEEDS_REVIEW"
    path=payload["database_path"]
    if not isinstance(path,str) or not path:
        return "NEEDS_REVIEW"
    try:
        result=await asyncio.to_thread(preflight,path)
    except (OSError,ValueError):
        return "NEEDS_REVIEW"
    return "DONE" if result["ready"] else "NEEDS_REVIEW"

SAFE_HANDLERS={"migration_preflight":migration_preflight_handler}
