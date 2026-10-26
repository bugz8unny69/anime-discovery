"""Trusted shared composition for workers serving dashboard/ADM action jobs."""
from src.nextgen.jobs.cleanup_canceled_operation_job import registration as cleanup
from src.nextgen.jobs.keep_media_job import registration as keep
from src.nextgen.jobs.refresh_jellyfin_job import registration as refresh
from src.nextgen.post_keep_cleanup import registration as cleanup_kept


from src.nextgen.jobs.enrich_shoko_job import registration as shoko
from src.nextgen.decision_download_cleanup import registration as cleanup_download
from src.nextgen.jobs.reject_media_job import registration as reject
from src.nextgen.jobs.keep_batch_job import registration as keep_batch
from src.nextgen.jobs.reject_batch_job import registration as reject_batch
from src.nextgen.jobs.cleanup_batch_download_job import registration as cleanup_batch
from src.nextgen.acquisition.metainfo_source import make_batch_reader

def registrations(secrets,*,read_batch_metainfo=None):
    if read_batch_metainfo is None:read_batch_metainfo=make_batch_reader()
    return (cleanup(secrets),keep(secrets),reject(),keep_batch(secrets),reject_batch(),
            cleanup_batch(read_batch_metainfo,secrets),refresh(secrets),cleanup_kept(secrets),cleanup_download(secrets),shoko(secrets))
