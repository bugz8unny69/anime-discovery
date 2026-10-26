"""One-shot, lease-fenced batch torrent submission journal.

Never sends network requests. Records UNCERTAIN *before* an external add
attempt, returning a process-local one-use permit only on first insertion.
A restart can only reconcile the same record: it can never rearm a send.
"""
from dataclasses import dataclass,field
from pathlib import PurePosixPath
import hashlib
import json
import secrets
import threading

from src.nextgen.acquisition.metadata import BatchInventory, AcquisitionConflict
from src.nextgen.acquisition.settings import DownloadOptions
from src.nextgen.acquisition.submission import Observation, ClientInvalid
from src.nextgen.acquisition.transfers import STOPPED, CHECKING
from src.nextgen.history import append_job_history, integer
from src.nextgen.storage.batch_acquisition_candidate import (
    BatchAcquisitionCandidate, _candidate,
)
from src.nextgen.storage.job_queue import JobQueue
from src.nextgen.storage.sqlite import transaction


@dataclass(frozen=True)
class BatchSubmissionIntent:
    candidate: BatchAcquisitionCandidate = field(repr=False)
    inventory: BatchInventory = field(repr=False)
    options: DownloadOptions = field(repr=False)
    marker: str = field(repr=False)
    state: str
    fingerprint: str
    api_major: int
    def __post_init__(self):
        if (type(self.candidate) is not BatchAcquisitionCandidate
                or type(self.inventory) is not BatchInventory
                or type(self.options) is not DownloadOptions
                or type(self.marker) is not str or len(self.marker)!=32
                or any(x not in '0123456789abcdef' for x in self.marker)
                or self.state not in ('UNCERTAIN','EXTERNAL','REVIEW','OWNED_STOPPED')
                or type(self.fingerprint) is not str or len(self.fingerprint)!=64
                or any(x not in '0123456789abcdef' for x in self.fingerprint)
                or type(self.api_major) is not int or self.api_major not in (4,5)):
            raise ClientInvalid()
        if (self.candidate.info_hash,self.candidate.info_sha256)!=(
                self.inventory.info_hash,self.inventory.info_sha256):
            raise AcquisitionConflict()


class BatchSendPermit:
    """Single use in one process; never reconstructed from SQLite on restart."""
    def __init__(self,fingerprint):
        self.fingerprint=fingerprint
        self._lock=threading.Lock()
        self._used=False

    def take(self,intent):
        with self._lock:
            if (self._used or type(intent) is not BatchSubmissionIntent
                    or intent.fingerprint!=self.fingerprint
                    or intent.state!='UNCERTAIN'):
                raise ClientInvalid()
            self._used=True


def _target(options,marker):
    if type(options) is not DownloadOptions:raise AcquisitionConflict()
    return DownloadOptions(options.base_url,
                           str(PurePosixPath(options.download_root)/('ad-'+marker)),
                           options.category,options.timeout_seconds)


def _fingerprint(candidate,inventory,options,marker,major):
    return hashlib.sha256(json.dumps({
        'plan':candidate.plan_id,'reservation_job':candidate.reservation_job_id,
        'info_hash':inventory.info_hash,'info_sha256':inventory.info_sha256,
        'files_sha256':hashlib.sha256(inventory.json().encode('utf-8')).hexdigest(),
        'planned_episodes':candidate.planned_episodes,
        'probe':candidate.probe_index,
        'marker':marker,'base_url':options.base_url,
        'save_path':options.download_root,'category':options.category,
        'timeout':options.timeout_seconds,'api_major':major,
        'stopped':True,'auto_tmm':False,'skip_checking':False,
        'content_layout':'Original','use_download_path':False,
    },sort_keys=True,separators=(',',':')).encode('utf-8')).hexdigest()


def _intent(db,candidate,inventory):
    row=db.execute(
        'SELECT reservation_job_id,info_hash,info_sha256,ownership_marker,'
        'base_url,save_path,category,timeout_seconds,api_major,fingerprint,state '
        'FROM batch_torrent_submissions WHERE plan_id=?',(candidate.plan_id,)).fetchone()
    if row is None:return None
    reservation,info_hash,sha,marker,*rest=row
    options=DownloadOptions(*rest[:4])
    major,fingerprint,state=rest[4:]
    if ((reservation,info_hash,sha)!=(candidate.reservation_job_id,
                                      inventory.info_hash,inventory.info_sha256)
            or _fingerprint(candidate,inventory,options,marker,major)!=fingerprint):
        raise AcquisitionConflict()
    return BatchSubmissionIntent(candidate,inventory,options,marker,state,fingerprint,major)


def _classify(intent,observation):
    if observation is None:return 'UNCERTAIN','TORRENT_SUBMISSION_UNCERTAIN'
    if type(observation) is not Observation:raise ClientInvalid()
    if (observation.info_hash!=intent.inventory.info_hash
            or observation.save_path.rstrip('/')!=intent.options.download_root
            or observation.category!=intent.options.category
            or observation.auto_tmm is not False
            or 'ad-'+intent.marker not in observation.tags
            or any(t.startswith('ad-') and t!='ad-'+intent.marker
                   for t in observation.tags)):
        return 'REVIEW','TORRENT_PROVENANCE_CONFLICT'
    if observation.state in CHECKING or not observation.files:
        return 'UNCERTAIN','TORRENT_SUBMISSION_UNCERTAIN'
    if observation.files!=intent.inventory.files or observation.state not in STOPPED:
        return 'REVIEW','TORRENT_PROVENANCE_CONFLICT'
    return 'OWNED_STOPPED','TORRENT_STOPPED_CONFIRMED'


class BatchSubmissionJournal:
    def __init__(self,database,*,clock=None):
        self.queue=JobQueue(database,clock=clock)

    def _owns(self,db,claim):
        if claim.kind!='SUBMIT_BATCH':raise AcquisitionConflict()
        self.queue._owns(db,claim,self.queue.now())

    def load(self,claim,reservation_job_id,inventory):
        integer(reservation_job_id,positive=True)
        if type(inventory) is not BatchInventory:raise AcquisitionConflict()
        with self.queue.connection() as db,transaction(db):
            self._owns(db,claim)
            candidate=_candidate(db,reservation_job_id,inventory)
            intent=_intent(db,candidate,inventory)
            self._owns(db,claim)
            return candidate,intent

    def authorize(self,claim,candidate,inventory,options,api_major,present,revision):
        if (type(candidate) is not BatchAcquisitionCandidate
                or type(inventory) is not BatchInventory
                or type(options) is not DownloadOptions
                or type(api_major) is not int or api_major not in (4,5)
                or type(present) is not bool):
            raise ValueError('Trusted batch source, qB client and observation required')
        integer(revision,positive=True)
        with self.queue.connection() as db,transaction(db):
            self._owns(db,claim)
            now=self.queue.now()
            if _candidate(db,candidate.reservation_job_id,inventory)!=candidate:
                raise AcquisitionConflict()
            prior=_intent(db,candidate,inventory)
            if prior is not None:
                if prior.options!=_target(options,prior.marker) or prior.api_major!=api_major:
                    raise AcquisitionConflict()
                return prior,None,()
            # Forbid a second journal for this hash even if an earlier
            # journal is in an uncertain or reviewed state.
            if db.execute('SELECT 1 FROM batch_torrent_submissions WHERE info_hash=?',
                          (inventory.info_hash,)).fetchone():
                raise AcquisitionConflict()
            marker=secrets.token_hex(16)
            target=_target(options,marker)
            fingerprint=_fingerprint(candidate,inventory,target,marker,api_major)
            state,reason=(('EXTERNAL','TORRENT_ALREADY_PRESENT') if present
                          else ('UNCERTAIN','TORRENT_SUBMISSION_UNCERTAIN'))
            db.execute(
                'INSERT INTO batch_torrent_submissions('
                'plan_id,reservation_job_id,first_job_id,first_attempt,info_hash,info_sha256,'
                'ownership_marker,base_url,save_path,category,timeout_seconds,api_major,'
                'fingerprint,configuration_revision,state,reason_code,created_at_ms,updated_at_ms)'
                ' VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                (candidate.plan_id,candidate.reservation_job_id,claim.job_id,claim.attempt,
                 inventory.info_hash,inventory.info_sha256,marker,target.base_url,
                 target.download_root,target.category,target.timeout_seconds,api_major,
                 fingerprint,revision,state,reason,now,now))
            receipt=append_job_history(
                db,job_id=claim.job_id,event_code='TORRENT_INTENT_RECORDED',
                reason_code=reason,component='worker',occurred_at_ms=now,
                details={'attempt':claim.attempt})
            self._owns(db,claim)
            intent=BatchSubmissionIntent(candidate,inventory,target,marker,state,fingerprint,api_major)
            return intent,(None if present else BatchSendPermit(fingerprint)),(receipt,)

    def guard_send(self,claim,intent):
        if type(intent) is not BatchSubmissionIntent:raise AcquisitionConflict()
        with self.queue.connection() as db,transaction(db):
            self._owns(db,claim)
            candidate=_candidate(db,intent.candidate.reservation_job_id,intent.inventory)
            current=_intent(db,candidate,intent.inventory)
            if (current!=intent or current.state!='UNCERTAIN'
                    or db.execute('SELECT first_job_id,first_attempt FROM batch_torrent_submissions '
                                  'WHERE plan_id=?',(candidate.plan_id,)).fetchone()
                    !=(claim.job_id,claim.attempt)):
                raise AcquisitionConflict()
            self._owns(db,claim)

    def observe(self,claim,intent,observation):
        if type(intent) is not BatchSubmissionIntent:raise AcquisitionConflict()
        with self.queue.connection() as db,transaction(db):
            self._owns(db,claim)
            now=self.queue.now()
            candidate=_candidate(db,intent.candidate.reservation_job_id,intent.inventory)
            current=_intent(db,candidate,intent.inventory)
            if current is None or current.fingerprint!=intent.fingerprint:
                raise AcquisitionConflict()
            if current.state in ('EXTERNAL','REVIEW','OWNED_STOPPED'):
                return current.state,(),()
            if current.state!=intent.state:
                return current.state,(),()
            state,reason=_classify(current,observation)
            receipt=()
            if state!=current.state:
                db.execute('UPDATE batch_torrent_submissions SET state=?,reason_code=?,'
                           'updated_at_ms=? WHERE plan_id=?',
                           (state,reason,now,candidate.plan_id))
                receipt=(append_job_history(
                    db,job_id=claim.job_id,event_code='TORRENT_RECONCILED',
                    reason_code=reason,component='worker',occurred_at_ms=now,
                    details={'attempt':claim.attempt}),)
            self._owns(db,claim)
            return state,reason,receipt
