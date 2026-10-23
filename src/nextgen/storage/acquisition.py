"""Immutable source inventory/intent publication under fenced worker completion."""
from pathlib import PurePosixPath
import sqlite3
import time
import uuid

from src.nextgen.acquisition.contracts import AcquisitionInput, AcquisitionProposal
from src.nextgen.acquisition.metadata import AcquisitionConflict, MetadataInvalid, SourceMissing, infohash
from src.nextgen.episode_reservations import ReservationConflict
from src.nextgen.history import append_job_history, integer
from src.nextgen.job_contracts import parse_payload
from src.nextgen.providers.parsing import release_title, norm
from src.nextgen.providers.release_mapping import declared_episode
from src.nextgen.release_contracts import ReleaseNotReady
from src.nextgen.storage.episode_reservations import _facts as episode_facts
from src.nextgen.storage.job_queue import QueueUnavailable
from src.nextgen.storage.migrations import LATEST_VERSION, MigrationError, _open


def _source(db,evaluation_job_id,event_id):
    row=db.execute("SELECT s.reservation_id,s.owner_job_id,s.verification_id,s.plan_id,s.anidb_id,s.anidb_episode_id,"
        "s.tvdb_series_id,s.tvdb_season,s.tvdb_episode,s.tvdb_episode_id,r.anidb_episode_number,r.release_sha256,"
        "a.title,CASE WHEN length(e.raw_body)<=65536 THEN e.raw_body ELSE NULL END "
        "FROM episode_reservations s JOIN jobs j ON j.job_id=s.owner_job_id "
        "JOIN release_verifications r ON r.verification_id=s.verification_id "
        "JOIN identified_anime a ON a.anidb_id=s.anidb_id JOIN incoming_events e ON e.event_id=j.event_id "
        "WHERE s.evaluation_job_id=? AND j.event_id=? AND j.kind='RESERVE_EPISODE' AND j.state='DONE'",
        (evaluation_job_id,event_id)).fetchone()
    if row is None:raise AcquisitionConflict()
    try:proof=episode_facts(db,evaluation_job_id,event_id)
    except ReservationConflict:raise AcquisitionConflict() from None
    if not proof.selected or row[2:10]!=(proof.verification_id,proof.plan_id,proof.anidb_id,proof.anidb_episode_id,
                                       proof.tvdb_series_id,proof.tvdb_season,proof.tvdb_episode,proof.tvdb_episode_id):
        raise AcquisitionConflict()
    try:
        document=parse_payload(row[13].decode('utf-8'))
        torrent_hash=infohash(document.get('torrent_infohash'))
    except (ValueError,TypeError,AttributeError,UnicodeError):raise SourceMissing() from None
    return AcquisitionInput(row[0],row[1],evaluation_job_id,event_id,torrent_hash,row[11],row[10],row[7],row[8],row[12])


def load_acquisition_input(database,evaluation_job_id,event_id):
    integer(evaluation_job_id,positive=True)
    integer(event_id,positive=True)
    db=None
    try:
        db=_open(database,readonly=True)
        if db.execute('PRAGMA user_version').fetchone()[0]!=LATEST_VERSION:raise QueueUnavailable()
        return _source(db,evaluation_job_id,event_id)
    except (OSError,sqlite3.Error,MigrationError):raise QueueUnavailable() from None
    finally:
        if db is not None:db.close()


def validate_declaration(source,manifest):
    """Filename alignment only; never proves bytes, audio or acquisition rights."""
    try:
        name=PurePosixPath(manifest.files[manifest.selected_index].path).stem
        origin,season,episode=declared_episode(name)
        aliases,_=release_title(name)
        if norm(source.title) not in {norm(a) for a in aliases}:raise MetadataInvalid()
        if (origin=='anidb' and episode!=source.anidb_episode_number) or (origin=='tvdb' and (season,episode)!=(source.tvdb_season,source.tvdb_episode)):
            raise MetadataInvalid()
    except (ValueError,TypeError,IndexError,ReleaseNotReady):raise MetadataInvalid() from None


def persist_acquisition(db,claim,value):
    if not db.in_transaction or type(value) is not AcquisitionProposal:
        raise ValueError('worker transaction and typed acquisition facts required')
    source,manifest=value.source,value.manifest
    if claim.event_id!=source.event_id or _source(db,source.evaluation_job_id,claim.event_id)!=source:
        raise AcquisitionConflict()
    validate_declaration(source,manifest)
    encoded=manifest.json()
    rows=db.execute("SELECT job_id,reservation_id,info_hash,info_sha256,manifest_json,configuration_revision "
                    "FROM acquisition_plans WHERE reservation_id=? OR info_hash=?",
                    (source.reservation_id,source.info_hash)).fetchall()
    expected=(claim.job_id,source.reservation_id,manifest.info_hash,manifest.info_sha256,encoded,value.configuration_revision)
    now=integer(time.time_ns()//1000000)
    if rows:
        if len(rows)!=1 or rows[0]!=expected:raise AcquisitionConflict()
    else:
        db.execute("INSERT INTO acquisition_plans(job_id,reservation_id,info_hash,info_sha256,manifest_json,"
            "submission_marker,configuration_revision,prepared_at_ms) VALUES(?,?,?,?,?,?,?,?)",
            (*expected[:5],uuid.uuid4().hex,expected[5],now))
    return append_job_history(db,job_id=claim.job_id,event_code='ACQUISITION_PREPARED',reason_code='ACQUISITION_PLAN_READY',
                              component='worker',occurred_at_ms=now,details={'attempt':claim.attempt})
