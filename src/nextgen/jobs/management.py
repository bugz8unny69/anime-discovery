"""Trusted shared composition for workers serving dashboard/ADM action jobs."""
from src.nextgen.jobs.cleanup_canceled_operation_job import registration as cleanup
from src.nextgen.jobs.keep_media_job import registration as keep


from src.nextgen.jobs.reject_media_job import registration as reject

def registrations(secrets):
    return (cleanup(secrets),keep(),reject())
