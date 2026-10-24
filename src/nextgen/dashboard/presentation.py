"""Trusted display registrations reused by API views; no job execution."""
from src.nextgen.handlers import HandlerCatalog
from src.nextgen.jobs.identify_anime_job import DEFINITION as identify
from src.nextgen.jobs.verify_release_job import DEFINITION as verify
from src.nextgen.jobs.evaluate_trial_job import DEFINITION as evaluate
from src.nextgen.jobs.reserve_episode_job import DEFINITION as reserve
from src.nextgen.jobs.prepare_acquisition_job import DEFINITION as prepare
from src.nextgen.jobs.submit_torrent_job import DEFINITION as submit
from src.nextgen.jobs.download_torrent_job import DEFINITION as download
from src.nextgen.jobs.verify_media_job import DEFINITION as media
from src.nextgen.jobs.keep_media_job import DEFINITION as keep
from src.nextgen.jobs.cleanup_canceled_operation_job import DEFINITION as cleanup

HANDLERS=HandlerCatalog((identify,verify,evaluate,reserve,prepare,submit,download,media,keep,cleanup))
