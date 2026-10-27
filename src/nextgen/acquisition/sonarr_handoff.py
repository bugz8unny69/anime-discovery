"""Side-effect-free Sonarr candidate admission before existing acquisition preparation.

This is NOT a job route or a torrent send permit. A verified incoming release
and active episode reservation must still supply AcquisitionInput through the
existing fenced persistence layer; this module cannot create them.
"""
from dataclasses import dataclass, field

from src.nextgen.acquisition.contracts import AcquisitionInput
from src.nextgen.acquisition.metadata import AcquisitionConflict, Manifest, parse_metainfo
from src.nextgen.acquisition.settings import SizeLimits
from src.nextgen.acquisition.sonarr_search import DiscoveryPolicy, Release, SearchResult, _magnet_hash
from src.nextgen.sonarr_episode import VerifiedEpisode
from src.nextgen.storage.acquisition import validate_declaration


@dataclass(frozen=True)
class AdmittedCandidate:
    """Transient verified observation; no durable permission or source URL."""
    source: AcquisitionInput
    manifest: Manifest = field(repr=False)
    resolution: int = 0
    seeders: int = 0


def admit_candidate(*, result, release, identity, source, metainfo, policy,
                    limits=SizeLimits()):
    """Fail closed unless Sonarr discovery and existing verified source agree.

    The caller obtains source only via load_acquisition_input, which enforces
    existing event, reservation and verified-release provenance. The returned
    value must still pass PREPARE_ACQUISITION and the submission journal.
    Never passes magnet URLs into qBittorrent or stores credentials.
    """
    if (type(result) is not SearchResult or type(release) is not Release
            or type(identity) is not VerifiedEpisode
            or type(source) is not AcquisitionInput
            or type(policy) is not DiscoveryPolicy or type(limits) is not SizeLimits
            or type(metainfo) is not bytes):
        raise AcquisitionConflict()
    if (not any(item is release for item in result.candidates)
            or source.tvdb_season != identity.tvdb_season
            or source.tvdb_episode != identity.tvdb_episode
            or source.info_hash != release.info_hash
            or not policy.accepts(release)
            or _magnet_hash(release.magnet_url) != source.info_hash):
        raise AcquisitionConflict()
    manifest = parse_metainfo(metainfo, source.info_hash)
    validate_declaration(source, manifest)
    limits.admit(manifest.files[manifest.selected_index].size)
    return AdmittedCandidate(source, manifest, release.resolution, release.seeders)
