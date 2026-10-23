"""Required provider configuration and worker composition; no HTTP at startup."""
from functools import partial

from src.nextgen.configuration import ConfigurationStore
from src.nextgen.configuration_schema import ConfigurationError
from src.nextgen.job_contracts import Policy, Registry
from src.nextgen.jobs.identify_anime_job import registration
from src.nextgen.jobs.verify_release_job import KIND as RELEASE_KIND, registration as release_registration
from src.nextgen.jobs.evaluate_trial_job import KIND as TRIAL_KIND, registration as trial_registration
from src.nextgen.jobs.reserve_episode_job import KIND as RESERVE_KIND, registration as reserve_registration
from src.nextgen.jobs.prepare_acquisition_job import KIND as PREPARE_KIND, registration as prepare_registration
from src.nextgen.jobs.submit_torrent_job import KIND as SUBMIT_KIND, registration as submit_registration
from src.nextgen.jobs.download_torrent_job import KIND as DOWNLOAD_KIND, registration as download_registration
from src.nextgen.jobs.management import registrations as management_registrations
from src.nextgen.providers.errors import ProviderConfigurationError
from src.nextgen.providers.http import Options
from src.nextgen.providers.identity import ClientPool, make_resolver
from src.nextgen.providers.releases import make_verifier
from src.nextgen.secrets import SecretStore
from src.nextgen.worker import Worker, blocking, serve_worker


def options_from_configuration(configuration):
    try:
        return Options(configuration.value("anidb.client_name"),
                       configuration.value("anidb.client_version"),
                       configuration.value("providers.timeout_seconds"))
    except ConfigurationError:
        raise ProviderConfigurationError() from None


def validate_provider_configuration(configuration, *, secrets):
    options_from_configuration(configuration)
    secrets.tvdb_credentials()


async def build_identity_worker(config_directory, *, additional_registrations=(), release_kind=None,
                                policy=Policy(), logger=None, read_metainfo=None):
    """Validate required local settings, then return an unstarted worker.

    Call close() if not serving it. Both providers are mandatory for this
    composition. Generic Worker still supports unrelated explicitly installed
    jobs without requiring identity-provider credentials.
    """
    store = ConfigurationStore(config_directory)
    secrets = SecretStore(config_directory)
    startup = await blocking(store.read)
    prepare = partial(validate_provider_configuration,secrets=secrets)
    await blocking(prepare,startup)  # Missing configuration fails before claims.
    pool=ClientPool()
    resolve = make_resolver(options_from_configuration,secrets.tvdb_credentials,client_pool=pool)
    verify = make_verifier(options_from_configuration,secrets.tvdb_credentials,client_pool=pool)
    preparation=() if read_metainfo is None else (prepare_registration(read_metainfo,submission_kind=SUBMIT_KIND),
                                                submit_registration(read_metainfo,secrets,transfer_kind=DOWNLOAD_KIND),
                                                download_registration(secrets))
    registry = Registry((registration(resolve,release_kind=RELEASE_KIND if release_kind is None else release_kind),
                         release_registration(verify,trial_kind=TRIAL_KIND),trial_registration(reservation_kind=RESERVE_KIND),reserve_registration(preparation_kind=None if read_metainfo is None else PREPARE_KIND),
                         *preparation,*management_registrations(secrets),*additional_registrations))
    return Worker(store,startup,registry,policy=policy,logger=logger,prepare=prepare)


async def run_identity_worker(config_directory, *, additional_registrations=(), release_kind=None,
                              policy=Policy(), read_metainfo=None):
    worker = await build_identity_worker(config_directory,additional_registrations=additional_registrations,
                                         release_kind=release_kind,policy=policy,read_metainfo=read_metainfo)
    await serve_worker(worker)
