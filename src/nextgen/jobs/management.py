"""Trusted shared composition for workers serving dashboard/ADM action jobs."""
from src.nextgen.jobs.cleanup_canceled_operation_job import registration as cleanup
from src.nextgen.jobs.keep_media_job import registration as keep
from src.nextgen.jobs.refresh_jellyfin_job import registration as refresh
from src.nextgen.post_keep_cleanup import registration as cleanup_kept


from src.nextgen.jobs.enrich_shoko_job import registration as shoko
from src.nextgen.decision_download_cleanup import registration as cleanup_download
from src.nextgen.jobs.reject_media_job import registration as reject

def registrations(secrets):
    return (cleanup(secrets),keep(secrets),reject(),refresh(secrets),cleanup_kept(secrets),cleanup_download(secrets),shoko(secrets))
