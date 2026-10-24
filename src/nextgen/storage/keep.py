"""Atomic, immutable staging-to-Keep approval evidence and fenced import journal.

All helpers operate under an existing caller-owned SQLite transaction; they
never contact Sonarr or access the filesystem. Uncertain external submissions
MUST remain IMPORT_INTENT and cannot be blindly submitted again.
"""
import hashlib
import json

from src.nextgen.staging import encoded
from src.nextgen.storage.cancellation import operation
from src.nextgen.storage.sqlite import transaction
from src.nextgen.storage.job_queue import JobQueue


class KeepReview(ValueError):
    reason_code = "KEEP_NOT_READY"
    def __init__(self):
        super().__init__("Keep requires one verified staged episode and exact TVDB mapping.")


def _positive(value):
    return type(value) is int and value > 0


def _approval(db, operation_id):
    """One published operation, with immutable stage and verified episode IDs."""
    rows = db.execute(
        "SELECT s.plan_id,s.job_id,s.manifest_json,s.receipts_json,"
        "r.anidb_id,r.anidb_episode_id,r.tvdb_series_id,r.tvdb_season,r.tvdb_episode,r.tvdb_episode_id "
        "FROM staging_publications s JOIN acquisition_plans p USING(plan_id) "
        "JOIN episode_reservations r USING(reservation_id) "
        "JOIN job_operation_members m ON m.job_id=s.job_id "
        "WHERE m.operation_id=? AND s.state='PUBLISHED'", (operation_id,)).fetchall()
    if len(rows) != 1:
        raise KeepReview()
    plan_id, stage_job_id, manifest_raw, receipts_raw, *ids = rows[0]
    if (not all(_positive(x) for i,x in enumerate(ids) if i!=3)
            or type(ids[3]) is not int or ids[3]<0):
        raise KeepReview()
    if db.execute("SELECT 1 FROM anime_review_decisions WHERE anidb_id=?", (ids[0],)).fetchone():
        raise KeepReview()
    try:
        manifest = json.loads(manifest_raw)
        receipts = json.loads(receipts_raw)
        entries = manifest["entries"]
        media = next((e for e in entries if e["role"]=="media"), None)
        if (not isinstance(manifest["root"],str) or not manifest["root"].startswith("/")
                or not isinstance(manifest["root_identity"],list)
                or len(manifest["root_identity"])!=2
                or type(entries) is not list or type(receipts) is not list
                or len(entries)!=3 or len(receipts)!=3 or not isinstance(media,dict)
                or not isinstance(manifest["source"],dict)
                or media["sha256"]!=manifest["source"]["sha256"]):
            raise KeepReview()
        if sorted(e["role"] for e in entries)!=["episode","media","series"]:
            raise KeepReview()
        for e,r in zip(entries,receipts):
            if (type(e) is not dict or type(r) is not dict
                    or e["role"]!=r["role"] or e["path"]!=r["path"]
                    or e["sha256"]!=r["sha256"] or e["size"]!=r["file"][2]
                    or type(r["file"]) is not list or len(r["file"])!=5):
                raise KeepReview()
        proof=next(r for r in receipts if r["role"]=="media")
        if proof["hash_checked"] is not False or proof["artifact"] is None:
            raise KeepReview()
    except (TypeError,KeyError,ValueError,StopIteration,IndexError):
        raise KeepReview() from None
    record={
        "stage_job_id":stage_job_id,
        "staging_plan_id":plan_id,
        "manifest":manifest,
        "receipts":receipts,
        "identity":dict(zip(("anidb_id","anidb_episode_id","tvdb_series_id",
                             "tvdb_season","tvdb_episode","tvdb_episode_id"),ids)),
    }
    raw=encoded(record)
    if len(raw.encode("utf-8"))>131072:raise KeepReview()
    return plan_id,raw,hashlib.sha256(raw.encode("utf-8")).hexdigest()


def approve(db, operation_id, keep_job_id, now):
    """Snapshot exact approved files/identity in the management-action transaction."""
    if not db.in_transaction or not _positive(operation_id) or not _positive(keep_job_id):
        raise KeepReview()
    if operation(db,keep_job_id)[0]==operation_id:
        # Control job must not be a member of the target operation.
        raise KeepReview()
    existing=db.execute("SELECT keep_job_id FROM keep_imports WHERE operation_id=?",(operation_id,)).fetchone()
    if existing:
        if existing!=(keep_job_id,):raise KeepReview()
        return
    plan,raw,digest=_approval(db,operation_id)
    db.execute("INSERT INTO keep_imports(operation_id,keep_job_id,staging_plan_id,approval_json,"
               "approval_sha256,phase,approved_at_ms,updated_at_ms) "
               "VALUES(?,?,?,?,?,'APPROVED',?,?)",(operation_id,keep_job_id,plan,raw,digest,now,now))


class KeepJournal:
    """Keep state transitions are fenced by the active worker lease."""
    def __init__(self,database):
        self.queue=JobQueue(database)

    def _row(self,db,claim):
        self.queue._owns(db,claim,self.queue.now())
        row=db.execute("SELECT operation_id,staging_plan_id,approval_json,approval_sha256,phase,"
            "sonarr_origin,sonarr_root,sonarr_profile,sonarr_timeout_seconds,configuration_revision,"
            "sonarr_series_id,selected_json,sonarr_command_id,library_evidence_json "
            "FROM keep_imports WHERE keep_job_id=?",(claim.job_id,)).fetchone()
        if row is None:raise KeepReview()
        approved=json.loads(row[2])
        if hashlib.sha256(row[2].encode()).hexdigest()!=row[3]:raise KeepReview()
        op=db.execute("SELECT operation_id FROM management_actions WHERE job_id=? AND action='KEEP'",(claim.job_id,)).fetchone()
        if op is None or op[0]!=row[0] or operation(db,claim.job_id)[0]==row[0]:raise KeepReview()
        if _approval(db,row[0])!=(row[1],row[2],row[3]):raise KeepReview()
        return {
            "operation_id":row[0], "approval":approved,"phase":row[4],
            "origin":row[5],"root":row[6],"profile":row[7],"timeout":row[8],
            "configuration_revision":row[9],"sonarr_id":row[10],
            "selected":None if row[11] is None else json.loads(row[11]),
            "command_id":row[12],"evidence":None if row[13] is None else json.loads(row[13])
        }

    def load(self,claim):
        with self.queue.connection() as db,transaction(db):
            return self._row(db,claim)

    def _change(self,claim,expected,phase,values):
        with self.queue.connection() as db,transaction(db):
            old=self._row(db,claim)
            if old["phase"]!=expected:raise KeepReview()
            names={"origin":"sonarr_origin","root":"sonarr_root","profile":"sonarr_profile",
                   "timeout":"sonarr_timeout_seconds","configuration_revision":"configuration_revision",
                   "sonarr_id":"sonarr_series_id","selected":"selected_json",
                   "command_id":"sonarr_command_id","evidence":"library_evidence_json"}
            if set(values)-set(names):raise KeepReview()
            fields=[names[k]+"=?" for k in values]
            params=[encoded(v) if k in ("selected","evidence") else v for k,v in values.items()]
            now=self.queue.now()
            sql="UPDATE keep_imports SET phase=?,"+",".join(fields+["updated_at_ms=?"])+" WHERE keep_job_id=? AND phase=?"
            db.execute(sql,(phase,*params,now,claim.job_id,expected))
            self._row(db,claim)

    def begin_series(self,claim,configuration):
        self._change(claim,"APPROVED","SERIES_INTENT",{
            "origin":configuration.value("sonarr.base_url"),
            "root":configuration.value("sonarr.root_folder"),
            "profile":configuration.value("sonarr.quality_profile_name"),
            "timeout":configuration.value("sonarr.timeout_seconds"),
            "configuration_revision":configuration.desired_revision})

    def series_ready(self,claim,sonarr_id):
        if not _positive(sonarr_id):raise KeepReview()
        self._change(claim,"SERIES_INTENT","SERIES_READY",{"sonarr_id":sonarr_id})

    def import_intent(self,claim,selected):
        if not isinstance(selected,list) or not selected:raise KeepReview()
        raw=encoded(selected)
        if len(raw.encode())>16384:raise KeepReview()
        self._change(claim,"SERIES_READY","IMPORT_INTENT",{"selected":selected})

    def accepted(self,claim,command_id):
        if not _positive(command_id):raise KeepReview()
        self._change(claim,"IMPORT_INTENT","COMMAND_ACCEPTED",{"command_id":command_id})

    def verified(self,db,claim,evidence):
        """Only invoke from the worker's atomic success/finish transaction."""
        if not db.in_transaction or type(evidence) is not dict:raise KeepReview()
        row=self._row(db,claim)
        if row["phase"]=="VERIFIED":
            if row["evidence"]!=evidence:raise KeepReview()
            return
        if row["phase"]!="COMMAND_ACCEPTED":raise KeepReview()
        raw=encoded(evidence)
        if len(raw.encode())>65536:raise KeepReview()
        db.execute("UPDATE keep_imports SET phase='VERIFIED',library_evidence_json=?,updated_at_ms=? "
                   "WHERE keep_job_id=? AND phase='COMMAND_ACCEPTED'",
                   (raw,self.queue.now(),claim.job_id))
