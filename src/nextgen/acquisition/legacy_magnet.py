"""Optional 4.2.x Sonarr magnet bootstrap in the existing PREPARE job.

Never produces a BEP3 Manifest or a torrent send permit for SUBMIT_TORRENT.
Observed inventories enter the existing transfer pipeline without another add.
"""
from src.nextgen.async_io import blocking
from src.nextgen.acquisition.contracts import AcquisitionProposal
from src.nextgen.acquisition.qbittorrent import Client as QBClient
from src.nextgen.acquisition.settings import (download_options, size_limits, DownloadConfigurationError,
    SizeLimitExceeded, SizeEvidenceMissing)
from src.nextgen.acquisition.metadata import (ObservedInventory, MetadataInvalid,
    AcquisitionConflict)
from src.nextgen.acquisition.submission import (
    ClientInvalid, ClientUnavailable, ClientAuthenticationFailed, ClientUnsupported,
)
from src.nextgen.acquisition.sonarr_search import (
    Client as SonarrClient, SearchReview, SearchUnavailable, _magnet_hash,
)
from src.nextgen.job_contracts import Outcome
from src.nextgen.storage.sonarr_magnet_intake import MagnetJournal
from src.nextgen.storage.sonarr_selection import acquisition_identity, SelectionConflict

PENDING=Outcome('defer','TORRENT_METADATA_WAITING',delay_ms=60000)


def make_bootstrap(secrets,*,client_factory=QBClient,journal_factory=MagnetJournal,
                   sonarr_factory=SonarrClient.from_context):
    """Only trusted worker composition supplies this callback; no webhook input."""
    async def bootstrap(source,context):
        configuration=context.configuration
        try:
            identity=await blocking(acquisition_identity,
                configuration.value('storage.database_path'),source)
            if identity is None:return None
            options=download_options(configuration)
            credentials=await blocking(secrets.qbittorrent_credentials)
            probe=client_factory(options,credentials)
            await blocking(probe.login)
            if probe.metadata_strategy!='legacy_poll':
                return None
            if context.cancelled.is_set():return PENDING
            journal=journal_factory(configuration.value('storage.database_path'))
            intent=await blocking(journal.existing,context.claim,source,
                                  options,probe.major)
            permit=None
            candidate=None
            if intent is None:
                # Only a NEW submission needs a fresh Sonarr search. Recovery
                # works even when Sonarr no longer lists the release.
                search=sonarr_factory(configuration,secrets)
                result=await blocking(search.search,identity)
                candidate=next((release for release in result.candidates
                                if release.info_hash==source.info_hash
                                and search.policy.accepts(release)
                                and _magnet_hash(release.magnet_url)==source.info_hash),
                               None)
                if candidate is None:return PENDING
                before=await blocking(probe.inspect,source.info_hash)
                if context.cancelled.is_set():return PENDING
                intent,permit,_=await blocking(
                    journal.authorize,context.claim,source,options,probe.major,
                    before is not None)
            if intent.state in ('REVIEW','EXTERNAL'):
                return Outcome('review','TORRENT_PROVENANCE_CONFLICT')
            owned=client_factory(intent.options,credentials)
            await blocking(owned.login)
            if permit is not None:
                # Once admitted, a failed or interrupted send is UNCERTAIN.
                # The journal never gives a second permit on replay.
                if context.cancelled.is_set():return PENDING
                await blocking(journal.guard,context.claim,intent)
                try:
                    await blocking(owned.add_legacy_magnet,
                                   candidate.magnet_url,intent,permit)
                except (ClientUnavailable,ClientInvalid,ClientAuthenticationFailed):
                    return PENDING
            current=await blocking(owned.inspect,source.info_hash)
            if current is None:return PENDING
            # Do not stop/restart any torrent without the exact journal tag.
            if (current.save_path.rstrip('/')!=intent.options.download_root
                    or current.category!=intent.options.category
                    or 'ad-'+intent.marker not in current.tags
                    or current.auto_tmm is not False):
                state=await blocking(journal.reconcile,context.claim,intent,current)
                if state=='REVIEW':
                    return Outcome('review','TORRENT_PROVENANCE_CONFLICT')
                return PENDING
            if (current.state not in ('pausedDL','pausedUP','stoppedDL','stoppedUP')
                    or intent.state=='OWNED_STOPPED'):
                snapshot=await blocking(owned.stop_legacy_metadata,intent)
            else:
                snapshot=await blocking(owned.poll_legacy_metadata,
                                        intent,context.cancelled)
            # Only the double-checked stopped snapshot can transition to
            # OWNED_STOPPED. A single opportunistic files read cannot.
            state=await blocking(journal.reconcile,context.claim,intent,snapshot)
            if state in ('REVIEW','EXTERNAL'):
                return Outcome('review','TORRENT_PROVENANCE_CONFLICT')
            if state=='OWNED_STOPPED' and snapshot is not None:
                inventory=ObservedInventory.from_observation(snapshot)
                size_limits(configuration).admit(
                    inventory.files[inventory.selected_index].size)
                await blocking(journal.capture,context.claim,intent,source,inventory)
                return Outcome(value=AcquisitionProposal(source,inventory,
                    configuration.desired_revision,size_limits(configuration),context.claim.job_id))
            return PENDING
        except SearchUnavailable:
            return Outcome('retry','SONARR_DISCOVERY_UNAVAILABLE')
        except SearchReview:
            return Outcome('review','SONARR_DISCOVERY_REVIEW')
        except ClientUnavailable:
            return Outcome('retry','DOWNLOAD_CLIENT_UNAVAILABLE')
        except (MetadataInvalid,AcquisitionConflict,SizeLimitExceeded,
                SizeEvidenceMissing) as exc:
            return Outcome('review',exc.reason_code)
        except (SelectionConflict,ClientInvalid,ClientAuthenticationFailed,
                ClientUnsupported,DownloadConfigurationError):
            return Outcome('review','TORRENT_PROVENANCE_CONFLICT')
    return bootstrap
