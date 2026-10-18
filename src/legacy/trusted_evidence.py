"""Offline evidence pinning prototype. Privileged adapters only; no source authentication.

Never ingest these records from RSS, torrent metadata, or ordinary API requests.
"""
import hashlib
import json
from collections.abc import Mapping
from approval_authorization import candidate_digest

SCHEMA = '''
CREATE TABLE trusted_evidence(
 revision_id INTEGER PRIMARY KEY REFERENCES mapping_revisions(id),
 candidate_json TEXT NOT NULL,
 evidence_json TEXT NOT NULL,
 evidence_sha256 TEXT NOT NULL,
 captured_at INTEGER NOT NULL CHECK(captured_at>0)
);
CREATE TRIGGER evidence_no_update BEFORE UPDATE ON trusted_evidence
 BEGIN SELECT RAISE(ABORT,'evidence immutable'); END;
CREATE TRIGGER evidence_no_delete BEFORE DELETE ON trusted_evidence
 BEGIN SELECT RAISE(ABORT,'evidence immutable'); END;
'''

class EvidenceError(ValueError):
    pass

def canonical(obj):
    try:
        return json.dumps(obj, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise EvidenceError('INVALID_JSON') from exc

def _positive(x):
    return type(x) is int and x > 0

def validate(candidate, evidence):
    """Validate shape and cross-bind source snapshots; NOT their authenticity."""
    if not isinstance(candidate, dict) or not isinstance(evidence, dict):
        raise EvidenceError('INVALID_INPUT')
    try:
        digest = candidate_digest(candidate)
    except ValueError as exc:
        raise EvidenceError('INVALID_CANDIDATE') from exc
    if set(evidence) != {'binding', 'snapshots'}:
        raise EvidenceError('INVALID_EVIDENCE')
    binding = evidence['binding']
    if not isinstance(binding, dict) or set(binding) != {'binding_id','series_id','anilist_id','state'}:
        raise EvidenceError('INVALID_BINDING')
    if (binding['state'] != 'ACTIVE' or
        any(binding[k] != candidate[k] for k in ('binding_id','series_id','anilist_id'))):
        raise EvidenceError('BINDING_MISMATCH')
    snaps = evidence['snapshots']
    if not isinstance(snaps, list) or len(snaps) != 2:
        raise EvidenceError('TWO_SNAPSHOTS_REQUIRED')
    seen = set()
    for snap in snaps:
        if not isinstance(snap, dict) or set(snap) != {'provider','series_id','anilist_id','binding_id','release_episode','release_season','canonical_season','canonical_episode','kind','source_record_id','retrieved_at'}:
            raise EvidenceError('INVALID_SNAPSHOT')
        provider = snap['provider']
        if provider not in ('anidb','sonarr') or provider in seen:
            raise EvidenceError('INVALID_PROVIDER')
        seen.add(provider)
        for key in ('series_id','anilist_id','binding_id','release_episode','release_season','canonical_season','canonical_episode'):
            if snap[key] != candidate.get(key):
                raise EvidenceError('SNAPSHOT_CONFLICT')
        if snap['kind'] != 'REGULAR' or not isinstance(snap['source_record_id'], str) or not snap['source_record_id'].strip() or not _positive(snap['retrieved_at']):
            raise EvidenceError('INVALID_SNAPSHOT')
    if seen != {'anidb','sonarr'}:
        raise EvidenceError('TWO_SOURCES_REQUIRED')
    return digest

def initialize(db):
    """Use only on disposable DB initialized by transactional_approval.initialize."""
    db.executescript(SCHEMA)

def pin(db, *, revision_id, candidate, evidence, captured_at):
    """Pin fixture data. Only privileged source adapters may invoke in production."""
    if not _positive(revision_id) or not _positive(captured_at) or db.in_transaction:
        raise EvidenceError('INVALID_PIN_CONTEXT')
    digest = validate(candidate, evidence)
    payload = canonical(candidate)
    snapshots = canonical(evidence)
    with db:
        row = db.execute('SELECT series_id,binding_id,candidate_sha256,status FROM mapping_revisions WHERE id=?', (revision_id,)).fetchone()
        if not row or row != (candidate['series_id'],candidate['binding_id'],digest,'PENDING'):
            raise EvidenceError('REVISION_MISMATCH')
        db.execute('INSERT INTO trusted_evidence VALUES (?,?,?,?,?)',
                   (revision_id,payload,snapshots,hashlib.sha256(snapshots.encode()).hexdigest(),captured_at))

def preflight(db, revision_id, *, now, max_age=86400):
    """Must execute INSIDE the approval write transaction to prevent TOCTOU."""
    row = db.execute('SELECT candidate_json,evidence_json,evidence_sha256,captured_at FROM trusted_evidence WHERE revision_id=?', (revision_id,)).fetchone()
    if not row:
        raise EvidenceError('EVIDENCE_NOT_PINNED')
    cj, ej, eh, captured = row
    if type(now) is not int or type(max_age) is not int or max_age <= 0 or now < captured or now - captured > max_age:
        raise EvidenceError('EVIDENCE_STALE')
    if hashlib.sha256(ej.encode()).hexdigest() != eh:
        raise EvidenceError('EVIDENCE_CORRUPT')
    candidate, evidence = json.loads(cj), json.loads(ej)
    digest = validate(candidate,evidence)
    revision = db.execute('SELECT series_id,binding_id,candidate_sha256,status FROM mapping_revisions WHERE id=?', (revision_id,)).fetchone()
    if not revision or revision != (candidate['series_id'],candidate['binding_id'],digest,'PENDING'):
        raise EvidenceError('REVISION_CHANGED')
    binding = db.execute('SELECT series_id,state FROM identity_bindings WHERE id=?', (candidate['binding_id'],)).fetchone()
    if binding != (candidate['series_id'],'ACTIVE'):
        raise EvidenceError('BINDING_REVOKED')
    entries = db.execute('SELECT release_episode,canonical_season,canonical_episode FROM mapping_entries WHERE revision_id=?', (revision_id,)).fetchall()
    if entries != [(candidate['release_episode'],candidate['canonical_season'],candidate['canonical_episode'])]:
        raise EvidenceError('MAPPING_ENTRIES_MISMATCH')
    for snap in evidence['snapshots']:
        if snap['retrieved_at'] > captured or captured - snap['retrieved_at'] > max_age:
            raise EvidenceError('SNAPSHOT_STALE')
    return True
