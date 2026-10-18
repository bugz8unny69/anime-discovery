"""Offline, fail-closed cancellation planner. No network or write operations."""
from dataclasses import dataclass
import re

_HASH = re.compile(r'(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64})\Z')

class PreflightError(ValueError):
    pass

@dataclass(frozen=True)
class Attempt:
    attempt_id: int
    series_id: int
    torrent_hash: str
    status: str
    generation: int

@dataclass(frozen=True)
class CancellationIntent:
    attempt_id: int
    series_id: int
    torrent_hash: str
    generation: int
    decision_id: int

@dataclass(frozen=True)
class Torrent:
    torrent_hash: str
    state: str

@dataclass(frozen=True)
class Plan:
    result: str
    torrent_hash: str
    attempt_id: int
    decision_id: int
    delete_files: bool = False
    executable: bool = False


def _positive(value):
    return type(value) is int and value > 0


def _hash(value):
    return isinstance(value, str) and bool(_HASH.fullmatch(value))


def plan(intent, attempt, inventory, *, decision_active, fresh_inventory, current_generation):
    """Produce a non-executable recommendation from caller-supplied snapshots.

    Caller MUST obtain attempt, decision, and inventory from trusted sources.
    This function cannot establish snapshot freshness or prevent a TOCTOU race.
    """
    if not isinstance(intent, CancellationIntent) or not isinstance(attempt, Attempt):
        raise PreflightError('Invalid intent or attempt type')
    if not all(_positive(x) for x in (intent.attempt_id, intent.series_id,
                                       intent.generation, intent.decision_id,
                                       attempt.attempt_id, attempt.series_id,
                                       attempt.generation, current_generation)):
        raise PreflightError('Invalid identifier or generation')
    if not _hash(intent.torrent_hash) or not _hash(attempt.torrent_hash):
        raise PreflightError('Invalid torrent hash')
    if (intent.attempt_id != attempt.attempt_id or
        intent.series_id != attempt.series_id or
        intent.torrent_hash.lower() != attempt.torrent_hash.lower() or
        intent.generation != attempt.generation or
        intent.generation != current_generation):
        raise PreflightError('Stale or mismatched attempt')
    if decision_active is not True:
        raise PreflightError('Decision not active')
    if fresh_inventory is not True:
        raise PreflightError('Fresh inventory required')
    if attempt.status not in ('QUEUED', 'DOWNLOADING', 'PAUSED', 'COMPLETED', 'CANCEL_PENDING'):
        raise PreflightError('Attempt not cancellable')
    if not isinstance(inventory, (list, tuple)):
        raise PreflightError('Invalid inventory')
    seen = set()
    matching = None
    for item in inventory:
        if not isinstance(item, Torrent) or not _hash(item.torrent_hash) or not isinstance(item.state, str) or not item.state:
            raise PreflightError('Invalid torrent inventory item')
        key = item.torrent_hash.lower()
        if key in seen:
            raise PreflightError('Duplicate torrent hash in inventory')
        seen.add(key)
        if key == intent.torrent_hash.lower():
            matching = item
    result = 'ALREADY_ABSENT' if matching is None else 'WOULD_REMOVE_TORRENT_ONLY'
    return Plan(result, intent.torrent_hash.lower(), intent.attempt_id, intent.decision_id)
