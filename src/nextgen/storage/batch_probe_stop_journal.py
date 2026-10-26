"""One-shot, lease-fenced stop after E01 completion and before changing priorities.

The stop intent is durably recorded before a single qB request. A crash or
timeout never creates a second permit. Only exact owned stopped observations
complete the handoff.
"""
from dataclasses import dataclass
import hashlib
import json

from src.nextgen.acquisition.metadata import AcquisitionConflict, BatchInventory
from src.nextgen.acquisition.transfers import (
    TransferPermit, TransferConflict, STOPPED, ACTIVE, CHECKING,
)
from src.nextgen.batch.probe_transfer import (
    verify_probe_snapshot, exact_probe_selection,
)
from src.nextgen.history import integer, append_job_history
from src.nextgen.storage.batch_acquisition_candidate import _candidate
from src.nextgen.storage.batch_submission_journal import _intent
from src.nextgen.storage.batch_transfer_journal import _record as transfer_record
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction


@dataclass(frozen=True)
class BatchStopRecord:
    fingerprint: str
    phase: str
    stop_job_id: int
    attempt: int
    reason_code: str


def _fingerprint(intent,transfer):
    return hashlib.sha256(json.dumps({
        'submission':intent.fingerprint,
        'transfer':transfer.fingerprint,
        'probe_index':intent.candidate.probe_index,
        'piece_size':transfer.piece_size,
        'job_kind':'STOP_BATCH_PROBE',
    },sort_keys=True,separators=(',',':')).encode()).hexdigest()


class BatchStopJournal:
    def __init__(self,database,*,clock=None):
        self.queue=JobQueue(database,clock=clock)

    def _source(self,db,claim,transfer_job_id):
        self.queue._owns(db,claim,self.queue.now())
        if claim.kind!='STOP_BATCH_PROBE':raise AcquisitionConflict()
        row=db.execute(
            "SELECT transfer.created_by_job_id,transfer.event_id,transfer.state,"
            "transfer.kind,o.state "
            "FROM jobs stopping "
            "JOIN jobs transfer ON transfer.job_id=stopping.created_by_job_id "
            "JOIN job_operation_members sm ON sm.job_id=stopping.job_id "
            "JOIN job_operation_members tm ON tm.job_id=transfer.job_id "
            "AND tm.operation_id=sm.operation_id "
            "JOIN job_operations o ON o.operation_id=sm.operation_id "
            "WHERE stopping.job_id=? AND transfer.job_id=?",
            (claim.job_id,transfer_job_id)).fetchone()
        if row is None or row[1:]!=(claim.event_id,'DONE','TRANSFER_BATCH','ACTIVE'):
            raise AcquisitionConflict()
        submission_id=row[0]
        source=db.execute(
            "SELECT reservation_job_id,info_hash,info_sha256,plan_id FROM "
            "batch_torrent_submissions WHERE first_job_id=? AND state='OWNED_STOPPED'",
            (submission_id,)).fetchone()
        if source is None:raise TransferConflict()
        return source

    def source_hash(self,claim,transfer_job_id):
        integer(transfer_job_id,positive=True)
        with self.queue.connection() as db,transaction(db):
            row=self._source(db,claim,transfer_job_id)
            return row[1]

    def _current(self,db,claim,transfer_job_id,inventory):
        if type(inventory) is not BatchInventory:raise TransferConflict()
        reservation,digest,sha,plan=self._source(db,claim,transfer_job_id)
        if (digest,sha)!=(inventory.info_hash,inventory.info_sha256):
            raise TransferConflict()
        candidate=_candidate(db,reservation,inventory)
        if candidate.plan_id!=plan:raise TransferConflict()
        intent=_intent(db,candidate,inventory)
        transfer=transfer_record(db,intent)
        if (intent is None or intent.state!='OWNED_STOPPED'
                or transfer is None or transfer.phase!='COMPLETE'
                or transfer.progress!=1 or transfer.transfer_job_id!=transfer_job_id):
            raise TransferConflict()
        row=db.execute(
            "SELECT fingerprint,phase,stop_job_id,first_attempt,reason_code "
            "FROM batch_probe_stops WHERE plan_id=?",(plan,)).fetchone()
        prior=None if row is None else BatchStopRecord(*row)
        if prior is not None and prior.fingerprint!=_fingerprint(intent,transfer):
            raise TransferConflict()
        return intent,transfer,prior

    def load(self,claim,transfer_job_id,inventory):
        with self.queue.connection() as db,transaction(db):
            return self._current(db,claim,transfer_job_id,inventory)

    def authorize(self,claim,transfer_job_id,intent,snapshot):
        with self.queue.connection() as db,transaction(db):
            current,transfer,record=self._current(
                db,claim,transfer_job_id,intent.inventory)
            if current!=intent:raise TransferConflict()
            if record is not None:return record,None,()
            verify_probe_snapshot(intent,snapshot)
            if (snapshot.piece_size!=transfer.piece_size
                    or not exact_probe_selection(intent,snapshot)
                    or snapshot.progress[transfer.selected_index]!=1):
                raise TransferConflict()
            now=self.queue.now()
            stopped=snapshot.observation.state in STOPPED
            phase='STOPPED' if stopped else 'STOP_UNCERTAIN'
            reason='TORRENT_STOPPED_CONFIRMED' if stopped else 'TORRENT_STOP_UNCERTAIN'
            if not stopped and snapshot.observation.state not in ACTIVE:
                raise TransferConflict()
            fingerprint=_fingerprint(intent,transfer)
            db.execute(
                "INSERT INTO batch_probe_stops(plan_id,stop_job_id,first_attempt,"
                "fingerprint,phase,reason_code,created_at_ms,updated_at_ms) "
                "VALUES(?,?,?,?,?,?,?,?)",
                (intent.candidate.plan_id,claim.job_id,claim.attempt,
                 fingerprint,phase,reason,now,now))
            audit=append_job_history(
                db,job_id=claim.job_id,event_code='TORRENT_TRANSFER_CHANGED',
                reason_code=reason,component='worker',occurred_at_ms=now,
                details={'attempt':claim.attempt})
            self.queue._owns(db,claim,self.queue.now())
            record=BatchStopRecord(fingerprint,phase,claim.job_id,claim.attempt,reason)
            return record,(None if stopped else TransferPermit(fingerprint,('stop',))),(audit,)

    def guard_send(self,claim,transfer_job_id,intent,record):
        with self.queue.connection() as db,transaction(db):
            current,transfer,stored=self._current(
                db,claim,transfer_job_id,intent.inventory)
            if (current!=intent or stored!=record
                    or stored.phase!='STOP_UNCERTAIN'
                    or (stored.stop_job_id,stored.attempt)!=(claim.job_id,claim.attempt)):
                raise TransferConflict()
            self.queue._owns(db,claim,self.queue.now())

    def observe(self,claim,transfer_job_id,intent,snapshot):
        with self.queue.connection() as db,transaction(db):
            current,transfer,record=self._current(
                db,claim,transfer_job_id,intent.inventory)
            if current!=intent or record is None:raise TransferConflict()
            if record.phase=='REVIEW':return record,()
            if record.phase=='STOPPED':return record,()
            if snapshot is None:return record,()
            verify_probe_snapshot(intent,snapshot)
            if (snapshot.piece_size!=transfer.piece_size
                    or not exact_probe_selection(intent,snapshot)
                    or snapshot.progress[transfer.selected_index]!=1):
                raise TransferConflict()
            if snapshot.observation.state not in STOPPED:
                return record,()
            now=self.queue.now()
            db.execute(
                "UPDATE batch_probe_stops SET phase='STOPPED',"
                "reason_code='TORRENT_STOPPED_CONFIRMED',updated_at_ms=? "
                "WHERE plan_id=?",
                (now,intent.candidate.plan_id))
            audit=append_job_history(
                db,job_id=claim.job_id,event_code='TORRENT_TRANSFER_CHANGED',
                reason_code='TORRENT_STOPPED_CONFIRMED',
                component='worker',occurred_at_ms=now,
                details={'attempt':claim.attempt})
            self.queue._owns(db,claim,self.queue.now())
            return BatchStopRecord(
                record.fingerprint,'STOPPED',record.stop_job_id,record.attempt,
                'TORRENT_STOPPED_CONFIRMED'),(audit,)
