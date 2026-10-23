"""Cancellation capabilities and per-operation runtime drain; no transport/UI."""
from contextlib import contextmanager
import fcntl
from src.nextgen.history import integer
from src.nextgen.maintenance import MaintenanceGate, MaintenanceBusy


class CancellationError(ValueError):
    reason_code='CANCELLATION_REVIEW'
    def __init__(self):super().__init__('Cancellation or cleanup needs review.')


class CancellationRequested(RuntimeError):
    reason_code='JOB_CANCELED'
    def __init__(self):super().__init__('This work has been canceled.')


class CleanupBusy(CancellationError):
    reason_code='CANCELLATION_DRAINING'
    def __init__(self):ValueError.__init__(self,'Waiting for active work to stop before cleanup.')


class OperationGate:
    """All workers hold shared drain protection across the whole handler attempt.

    Cleanup holds exclusive protection across external and file operations. Only
    this operation drains; ordinary maintenance admission is held separately.
    A process crash drops its lock. Expired SQLite leases alone do not prove drain.
    """
    def __init__(self,database):self.gate=MaintenanceGate(database)
    @contextmanager
    def hold(self,operation_id,*,cleanup=False):
        integer(operation_id,positive=True)
        with self.gate._directory() as directory:
            try:
                with self.gate._lock(directory,'operation-'+str(operation_id),fcntl.LOCK_EX if cleanup else fcntl.LOCK_SH):
                    yield
            except MaintenanceBusy:
                if cleanup:raise CleanupBusy() from None
                raise CancellationRequested() from None
