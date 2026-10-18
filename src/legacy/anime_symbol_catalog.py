"""Source-indexed diagnostic symbols for Anime Discovery.

This module documents literal codes found in the supplied Python snapshot.
Import and hover over Symbol.NAME; the source modules are not rewritten
except for the two audited episode verification files in this patch.
Unreviewed entries are marked explicitly and MUST NOT be treated as verified semantics.
"""
from enum import Enum

class Symbol(str, Enum):
    """Serialized codes and markers indexed from the supplied Python snapshot."""
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:92
    ACTION_OR_TARGET_MISMATCH = 'ACTION_OR_TARGET_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_trial_operator.py:73
    ADD_INTENT = 'ADD_INTENT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_trial_operator.py:81
    ADD_RESULT = 'ADD_RESULT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_trial_operator.py:77
    ADD_UNCERTAIN = 'ADD_UNCERTAIN'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:97
    ADMIN_APPROVAL_REQUIRES_AUTHENTICATED_GATEWAY = 'ADMIN_APPROVAL_REQUIRES_AUTHENTICATED_GATEWAY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:32, test_identity_evidence_assembly.py:10
    ADMIN_REVIEWED = 'ADMIN_REVIEWED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:37, test_anilist_adapter.py:38, anilist_adapter.py:29
    ADULT_STATUS_UNVERIFIED_OR_ADULT = 'ADULT_STATUS_UNVERIFIED_OR_ADULT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:788, api.guarded.candidate.py:802, api.candidate.py:782
    ALL_ATTEMPTS_TERMINAL = 'ALL_ATTEMPTS_TERMINAL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_cancellation_preflight.py:27, test_cancellation_preflight.py:33, cancellation_preflight.py:89 ...
    ALREADY_ABSENT = 'ALREADY_ABSENT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_attempt_evidence_fencing.py:68, attempt_evidence_fencing.py:112
    ALREADY_ABSENT_SIMULATION = 'ALREADY_ABSENT_SIMULATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trial_transition.py:109, test_trial_transition.py:67
    ALREADY_ACKNOWLEDGED = 'ALREADY_ACKNOWLEDGED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_production_copy_migration_rehearsal.py:27, production_copy_migration_rehearsal.py:68, production_copy_migration_rehearsal.py:108
    ALREADY_APPLIED = 'ALREADY_APPLIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trial_transition.py:64, test_trial_transition.py:31
    ALREADY_COMMITTED = 'ALREADY_COMMITTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_worker.py:65, cancellation_worker.py:74, cancellation_worker.py:91 ...
    ALREADY_GONE = 'ALREADY_GONE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_worker.py:101, test_cancellation_worker.py:58
    ALREADY_RECORDED = 'ALREADY_RECORDED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:33
    AMBIGUOUS_RELEASE_NUMBER = 'AMBIGUOUS_RELEASE_NUMBER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_identity.py:128, release_identity.py:174
    AMBIGUOUS_SEASON = 'AMBIGUOUS_SEASON'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:36
    ANIDB_EPISODE_IDENTITY_NOT_INDEPENDENTLY_CONFIRMED = 'ANIDB_EPISODE_IDENTITY_NOT_INDEPENDENTLY_CONFIRMED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:39
    ANIDB_IDENTITY_MISMATCH = 'ANIDB_IDENTITY_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:32
    ANIDB_TO_TVDB_EPISODE_OFFSET_UNSPECIFIED = 'ANIDB_TO_TVDB_EPISODE_OFFSET_UNSPECIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:35
    ANILIST_IDENTITY_MISMATCH = 'ANILIST_IDENTITY_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:122
    ANILIST_LOOKUP_FAILED = 'ANILIST_LOOKUP_FAILED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_config_runtime_v2.py:8, test_config_runtime_v2.py:12, test_config_runtime_v2.py:17 ...
    ANIME_CONFIG_DIR = 'ANIME_CONFIG_DIR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_dashboard_auth.py:6
    ANIME_DASHBOARD_AUTH_FILE = 'ANIME_DASHBOARD_AUTH_FILE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: dashboard.py:15
    ANIME_DASHBOARD_PASSWORD = 'ANIME_DASHBOARD_PASSWORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37
    ANIME_DASHBOARD_PUBLIC_URL = 'ANIME_DASHBOARD_PUBLIC_URL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: review_smoke_test.py:5, review_notifications.py:10
    ANIME_DISCOVERY_INBOX_DB = 'ANIME_DISCOVERY_INBOX_DB'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:47, api.py:49, test_api_client.py:13 ...
    ANIME_DISCOVERY_TOKEN = 'ANIME_DISCOVERY_TOKEN'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_verify.py:85, anime_identity_catalog.py:49, test_controller_identity_v7.py:14
    ANIME_IDENTITY_MAPPINGS = 'ANIME_IDENTITY_MAPPINGS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37, test_jellyfin_config_v4.py:17, test_jellyfin_config_v4.py:30
    ANIME_JELLYFIN_API_KEY = 'ANIME_JELLYFIN_API_KEY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_library_sync.py:38, test_jellyfin_config_v4.py:17, test_jellyfin_config_v4.py:30
    ANIME_JELLYFIN_URL = 'ANIME_JELLYFIN_URL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: review_notifications.py:20
    ANIME_NOTIFY_QUIET_HOURS = 'ANIME_NOTIFY_QUIET_HOURS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: review_smoke_test.py:7, review_notifications.py:12
    ANIME_NOTIFY_STATE = 'ANIME_NOTIFY_STATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37
    ANIME_NTFY_SERVER = 'ANIME_NTFY_SERVER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37
    ANIME_NTFY_TOKEN = 'ANIME_NTFY_TOKEN'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37
    ANIME_NTFY_TOPIC = 'ANIME_NTFY_TOPIC'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37, test_qb_config_v6.py:23, test_qb_config_v6.py:31
    ANIME_QB_PASSWORD = 'ANIME_QB_PASSWORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37, test_qb_config_v6.py:23, test_qb_config_v6.py:31
    ANIME_QB_USERNAME = 'ANIME_QB_USERNAME'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: review_notifications.py:19
    ANIME_REVIEW_POLL_SECONDS = 'ANIME_REVIEW_POLL_SECONDS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery.py:37
    ANIME_REVIEW_REMINDER_HOURS = 'ANIME_REVIEW_REMINDER_HOURS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: review_smoke_test.py:6, review_notifications.py:11
    ANIME_REVIEW_RESOLUTIONS = 'ANIME_REVIEW_RESOLUTIONS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_config_runtime_v2.py:12, anime_discovery.py:37
    ANIME_TVDB_API_KEY = 'ANIME_TVDB_API_KEY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_episode_v6.py:98, anime_identity_worker_v11.py:33, anime_identity_worker_v9.py:82 ...
    ANIME_TVDB_PIN = 'ANIME_TVDB_PIN'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:29
    ANIME_TYPE_OR_TITLE_NOT_CORROBORATED = 'ANIME_TYPE_OR_TITLE_NOT_CORROBORATED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v9.py:28
    APPLY_SERIES_ONLY = 'APPLY_SERIES_ONLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: transactional_approval.py:96
    APPROVAL_RACE = 'APPROVAL_RACE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: transactional_approval.py:83, test_approval_gateway.py:46, test_trusted_evidence.py:38 ...
    APPROVE_MAPPING = 'APPROVE_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1249, api.py:1313, api.py:1405 ...
    ATTEMPT_NOT_COMPLETED = 'ATTEMPT_NOT_COMPLETED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:119
    AUTOBRR_DISCOVERY_INBOX_TOKEN = 'AUTOBRR_DISCOVERY_INBOX_TOKEN'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:93
    AUTOMATIC_APPROVAL_DISABLED = 'AUTOMATIC_APPROVAL_DISABLED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_verification_v16.py:33, test_episode_verification_v16.py:16
    AUTO_VERIFIED_CANDIDATE = 'AUTO_VERIFIED_CANDIDATE'
    #: Meaning: Episode verifier is waiting for episode-order mapping evidence.
    #: Produced by / cause: V16 decision when mapping confirmation is missing.
    #: Effect: No automatic acquisition.
    #: Debug: Inspect audit episode_offset and mapping source.
    #: Seen at: anime_episode_verification_v16.py:36, test_episode_verification_v16.py:23
    AWAITING_MAPPING_EVIDENCE = 'AWAITING_MAPPING_EVIDENCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:52
    BINDING_MISMATCH = 'BINDING_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:108
    BINDING_REVOKED = 'BINDING_REVOKED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:15
    BIND_IDENTITY = 'BIND_IDENTITY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery_review_worker.py:49
    BLOCKED_STALE_OR_EXISTING_REVIEW_STATE = 'BLOCKED_STALE_OR_EXISTING_REVIEW_STATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: transactional_approval.py:68
    CALL_REQUIRES_NO_ACTIVE_TRANSACTION = 'CALL_REQUIRES_NO_ACTIVE_TRANSACTION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_preflight.py:74, test_cancellation_orchestration.py:23, test_cancellation_orchestration.py:62
    CANCEL_PENDING = 'CANCEL_PENDING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_worker.py:66, cancellation_orchestration.py:43, test_cancellation_orchestration.py:86
    CANCEL_REQUESTED = 'CANCEL_REQUESTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_release_catalog_gate.py:4, test_release_catalog_gate.py:13, canonical_provider_integration.py:136 ...
    CANDIDATE_ONLY = 'CANDIDATE_ONLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:140
    CATALOG_AGREEMENT_IS_NOT_RELEASE_FILE_PROVENANCE = 'CATALOG_AGREEMENT_IS_NOT_RELEASE_FILE_PROVENANCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:70
    CATALOG_AGREEMENT_NOT_RELEASE_PROVENANCE = 'CATALOG_AGREEMENT_NOT_RELEASE_PROVENANCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:43
    CATALOG_NOT_CANDIDATE = 'CATALOG_NOT_CANDIDATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:53
    CATALOG_PREFIX_CONFLICT = 'CATALOG_PREFIX_CONFLICT'
    #: Meaning: Shadow confidence evaluator did not return SHADOW_HIGH_CONFIDENCE.
    #: Produced by / cause: V16 compares the shadow decision.
    #: Effect: Episode approval is blocked.
    #: Debug: Inspect shadow blockers and scoring evidence.
    #: Seen at: anime_episode_verification_v16.py:12
    CONFIDENCE_POLICY_NOT_MET = 'CONFIDENCE_POLICY_NOT_MET'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_api_client.py:13, test_api_client.py:17
    CONFIG_DIR = 'CONFIG_DIR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_claims.py:105, cancellation_claims.py:119, cancellation_orchestration.py:76 ...
    CONFIRMED_ABSENT = 'CONFIRMED_ABSENT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:76
    CONFLICTING_CROSS_DATABASE_LINKS = 'CONFLICTING_CROSS_DATABASE_LINKS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:58, test_episode_reconciliation.py:61
    CONFLICTING_EPISODE = 'CONFLICTING_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:102
    CONFLICTING_EPISODE_ENTRIES = 'CONFLICTING_EPISODE_ENTRIES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_mapping.py:74, test_mapping_provenance.py:101, test_metadata_verification.py:31 ...
    CONFLICTING_EPISODE_MAP = 'CONFLICTING_EPISODE_MAP'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_crosscheck_v3.py:31, anime_identity_mapping_v4.py:60
    CONFLICTING_MEDIA_TYPE = 'CONFLICTING_MEDIA_TYPE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:39
    CONFLICTING_SEASON = 'CONFLICTING_SEASON'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: fresh_attempt_ownership.py:58
    CONTROLLER_CREATED = 'CONTROLLER_CREATED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:58, test_metadata_provenance_gate.py:18
    CROSS_REFERENCE_NOT_ATTESTED = 'CROSS_REFERENCE_NOT_ATTESTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:33
    CROSS_REFERENCE_NOT_REVIEWED = 'CROSS_REFERENCE_NOT_REVIEWED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_audit_v5.py:44
    DEFAULT_SEASON_MISSING_OR_INVALID = 'DEFAULT_SEASON_MISSING_OR_INVALID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:45, anime_identity_confidence_v14.py:45
    DEFAULT_SEASON_ONE = 'DEFAULT_SEASON_ONE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_cancellation_claims.py:58
    DELETED_FILES = 'DELETED_FILES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_persistence_v8.py:15, anime_identity_persistence_v8.py:58
    DRY_RUN_VALIDATED = 'DRY_RUN_VALIDATED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:90
    EMPTY_CATALOG = 'EMPTY_CATALOG'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: transactional_approval.py:78
    EMPTY_MAPPING = 'EMPTY_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:22
    EMPTY_RELEASE = 'EMPTY_RELEASE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1233, api.guarded.candidate.py:1247, api.candidate.py:1227
    ENGLISH_AUDIO_MISSING = 'ENGLISH_AUDIO_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:780, api.guarded.candidate.py:794, api.candidate.py:774
    EPISODE_ALREADY_DOWNLOADED = 'EPISODE_ALREADY_DOWNLOADED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:95
    EPISODE_ID_MISMATCH = 'EPISODE_ID_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:103
    EPISODE_LISTS_REQUIRED = 'EPISODE_LISTS_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_audit_v5.py:42, test_identity_audit_v5.py:33
    EPISODE_NOT_POSITIVE_INTEGER = 'EPISODE_NOT_POSITIVE_INTEGER'
    #: Meaning: Audit did not find an explicit episode offset.
    #: Produced by / cause: Episode mapping audit flag.
    #: Effect: Not proof that offset is zero.
    #: Debug: Inspect mapping source and parsed audit.
    #: Seen at: anime_identity_audit_v5.py:51, anime_episode_confidence_v13.py:38, test_identity_audit_v5.py:18
    EPISODE_OFFSET_NOT_EXPLICIT = 'EPISODE_OFFSET_NOT_EXPLICIT'
    #: Meaning: Legacy blocker: episode ordering mapping not confirmed.
    #: Produced by / cause: V16 emitted this when EXPLICIT_ZERO_OFFSET was absent.
    #: Effect: Approval remains blocked.
    #: Debug: Use EPISODE_ORDERING_MAPPING_NOT_CONFIRMED in new evaluations.
    #: Seen at: anime_episode_verification_v16.py:14, anime_episode_verification_v16.py:35
    EPISODE_OFFSET_NOT_INDEPENDENTLY_VERIFIED = 'EPISODE_OFFSET_NOT_INDEPENDENTLY_VERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:59
    EPISODE_OUTSIDE_CATALOG = 'EPISODE_OUTSIDE_CATALOG'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:37
    EPISODE_OVERRIDES_REQUIRE_INTERPRETATION = 'EPISODE_OVERRIDES_REQUIRE_INTERPRETATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_identity.py:197, test_release_identity.py:75, test_release_identity.py:83 ...
    EPISODE_PATTERN_RECOGNIZED = 'EPISODE_PATTERN_RECOGNIZED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_series_identity.py:53, release_identity.py:151, test_metadata_verification.py:33
    EPISODE_RANGE_OR_BATCH = 'EPISODE_RANGE_OR_BATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:782, api.guarded.candidate.py:796, api.candidate.py:776
    EPISODE_RETRY_REQUIRED = 'EPISODE_RETRY_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_audit_v5.py:48, test_identity_audit_v5.py:29
    EPISODE_SPECIFIC_MAPPING_REQUIRES_AUDIT = 'EPISODE_SPECIFIC_MAPPING_REQUIRES_AUDIT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:34
    EPISODE_SPECIFIC_RULES_REQUIRE_INTERPRETATION = 'EPISODE_SPECIFIC_RULES_REQUIRE_INTERPRETATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v12.py:60, anime_identity_worker_v15.py:81, test_identity_worker_v12.py:14 ...
    ERROR_RETRY_NO_STATUS_CHANGE = 'ERROR_RETRY_NO_STATUS_CHANGE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:100
    EVIDENCE_CORRUPT = 'EVIDENCE_CORRUPT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:45
    EVIDENCE_IDENTITY = 'EVIDENCE_IDENTITY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:85
    EVIDENCE_IDENTITY_MISMATCH = 'EVIDENCE_IDENTITY_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:95
    EVIDENCE_NOT_PINNED = 'EVIDENCE_NOT_PINNED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:98
    EVIDENCE_STALE = 'EVIDENCE_STALE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_persistence_v8.py:39, anime_identity_worker_v12.py:16, anime_identity_persistence_v8.py:74 ...
    EVIDENCE_UPDATED = 'EVIDENCE_UPDATED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:61
    EXACTLY_ONE_FILE_REQUIRED = 'EXACTLY_ONE_FILE_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:96
    EXPIRED_OR_NOT_YET_VALID = 'EXPIRED_OR_NOT_YET_VALID'
    #: Meaning: The V13 audit reports an explicitly present episode_offset equal to integer zero.
    #: Produced by / cause: V13 evaluate() emits this only after parsing the supplied offset.
    #: Effect: V16 requires it for episode verification; missing offset does not count as zero.
    #: Debug: Inspect episode_audit.episode_offset and mapping provenance.
    #: Seen at: anime_episode_verification_v16.py:13, anime_episode_confidence_v13.py:53
    EXPLICIT_ZERO_OFFSET = 'EXPLICIT_ZERO_OFFSET'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1104, api.py:1186, api.py:1098 ...
    FFPROBE_FAILED = 'FFPROBE_FAILED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:856, api.guarded.candidate.py:870, api.candidate.py:850
    FILE_CHANGED_SINCE_OBSERVATION = 'FILE_CHANGED_SINCE_OBSERVATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:71
    FILE_CONTENT_NOT_VERIFIED = 'FILE_CONTENT_NOT_VERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: deployment_candidate.py:25
    FILE_IDENTITY_RACE_NOT_CLOSED = 'FILE_IDENTITY_RACE_NOT_CLOSED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:846, api.py:1282, api.py:1351 ...
    FILE_NOT_ACCESSIBLE = 'FILE_NOT_ACCESSIBLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1527, api.guarded.candidate.py:1541, api.candidate.py:1521
    FILE_NOT_ACCESSIBLE_OR_UNSAFE = 'FILE_NOT_ACCESSIBLE_OR_UNSAFE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1039, api.guarded.candidate.py:1053, api.candidate.py:1033
    FILE_NOT_STABLE = 'FILE_NOT_STABLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:66
    FILE_SERIES_LABEL_MISSING = 'FILE_SERIES_LABEL_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1270, api.py:1342, api.py:1418 ...
    FILE_TOO_SMALL = 'FILE_TOO_SMALL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1021, api.guarded.candidate.py:1035, api.candidate.py:1015
    FILE_VERIFICATION_FAILED = 'FILE_VERIFICATION_FAILED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:44, test_anilist_adapter.py:45, anilist_adapter.py:64
    GRAPHQL_ERROR = 'GRAPHQL_ERROR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:67
    GUID_REUSED_WITH_DIFFERENT_RELEASE = 'GUID_REUSED_WITH_DIFFERENT_RELEASE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_plan.py:48
    HEALTH_INFORMATION_DISCLOSURE_REVIEW = 'HEALTH_INFORMATION_DISCLOSURE_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:57, source_provenance.py:59
    HTTP_REQUIRES_LOOPBACK = 'HTTP_REQUIRES_LOOPBACK'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_persistence_v8.py:23, canonical_provider_integration.py:101
    IDENTITY_CONFLICT = 'IDENTITY_CONFLICT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:31, test_episode_reconciliation.py:38, test_episode_reconciliation.py:39 ...
    IDENTITY_NOT_BOUND = 'IDENTITY_NOT_BOUND'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: dashboard.py:344
    IDENTITY_RECORDED = 'IDENTITY_RECORDED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:33, test_anilist_adapter.py:46, anilist_adapter.py:21
    ID_MISMATCH = 'ID_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:957, api.guarded.candidate.py:971, api.candidate.py:951
    IMPORTED_ATTEMPT_MISMATCH = 'IMPORTED_ATTEMPT_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:971, api.guarded.candidate.py:985, test_import_continuity.py:108 ...
    IMPORTED_FILE_VERIFICATION_FAILED = 'IMPORTED_FILE_VERIFICATION_FAILED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1318, api.guarded.candidate.py:1332, api.candidate.py:1312
    IMPORTED_PATH_MISSING = 'IMPORTED_PATH_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:70
    INBOX_CAPACITY_REACHED = 'INBOX_CAPACITY_REACHED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:50
    INBOX_DIRECTORY_MISSING = 'INBOX_DIRECTORY_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_mapping_v4.py:17
    INDEPENDENT_MAPPING_CORROBORATED = 'INDEPENDENT_MAPPING_CORROBORATED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:71
    INDEPENDENT_NUMBERING_EVIDENCE_REQUIRED = 'INDEPENDENT_NUMBERING_EVIDENCE_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:64, test_metadata_provenance_gate.py:20
    INDEPENDENT_PROVIDERS_REQUIRED = 'INDEPENDENT_PROVIDERS_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:32, anime_identity_confidence_v14.py:43, anime_identity_confidence_v14.py:41
    INDEPENDENT_SERIES_MAPPING_AND_ANIMATION_TITLE_MATCH = 'INDEPENDENT_SERIES_MAPPING_AND_ANIMATION_TITLE_MATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:82
    INDEPENDENT_SOURCES_REQUIRED = 'INDEPENDENT_SOURCES_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: live_boundary_patch.py:115
    INSUFFICIENT_AUTHENTICATED_PROVENANCE = 'INSUFFICIENT_AUTHENTICATED_PROVENANCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:102
    INVALID_ABSOLUTE_NUMBER = 'INVALID_ABSOLUTE_NUMBER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:57
    INVALID_ACTION = 'INVALID_ACTION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:59
    INVALID_ACTOR = 'INVALID_ACTOR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_gateway.py:26
    INVALID_ADMIN_KEY = 'INVALID_ADMIN_KEY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_verification.py:39
    INVALID_ALIASES = 'INVALID_ALIASES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:51, source_provenance.py:115, anilist_adapter.py:48
    INVALID_ANILIST_ID = 'INVALID_ANILIST_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:71
    INVALID_API_KEY = 'INVALID_API_KEY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:47, source_provenance.py:50, source_provenance.py:52
    INVALID_BASE_URL = 'INVALID_BASE_URL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:49
    INVALID_BINDING = 'INVALID_BINDING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:44, approval_authorization.py:33, approval_authorization.py:36
    INVALID_CANDIDATE = 'INVALID_CANDIDATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:126, source_provenance.py:129
    INVALID_CAPTURE_TIME = 'INVALID_CAPTURE_TIME'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:48
    INVALID_CLOCK = 'INVALID_CLOCK'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1143, api.guarded.candidate.py:1157, api.candidate.py:1137
    INVALID_DURATION = 'INVALID_DURATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_gateway.py:24, approval_authorization.py:83
    INVALID_ENVELOPE = 'INVALID_ENVELOPE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:63
    INVALID_EPISODE = 'INVALID_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:94, episode_reconciliation.py:98
    INVALID_EPISODE_ENTRY = 'INVALID_EPISODE_ENTRY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_mapping.py:47, canonical_mapping.py:56, canonical_mapping.py:64 ...
    INVALID_EPISODE_MAP = 'INVALID_EPISODE_MAP'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:100
    INVALID_EPISODE_NUMBER = 'INVALID_EPISODE_NUMBER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_audit_v5.py:46, anime_episode_confidence_v13.py:55
    INVALID_EPISODE_OFFSET = 'INVALID_EPISODE_OFFSET'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:71, test_metadata_provenance_gate.py:23, test_metadata_provenance_gate.py:24 ...
    INVALID_EPISODE_RECORD = 'INVALID_EPISODE_RECORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:46, episode_reconciliation.py:79
    INVALID_EVIDENCE = 'INVALID_EVIDENCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: mapping_provenance.py:30
    INVALID_EXPECTED_SERIES_ID = 'INVALID_EXPECTED_SERIES_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_verification.py:17
    INVALID_EXPECTED_TITLE = 'INVALID_EXPECTED_TITLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:40
    INVALID_GUID = 'INVALID_GUID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:29
    INVALID_ID = 'INVALID_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:53
    INVALID_IDENTIFIERS = 'INVALID_IDENTIFIERS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:50
    INVALID_IDENTITY = 'INVALID_IDENTITY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:42
    INVALID_INFO_HASH = 'INVALID_INFO_HASH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:40
    INVALID_INPUT = 'INVALID_INPUT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:30, trusted_evidence.py:32
    INVALID_JSON = 'INVALID_JSON'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:95
    INVALID_LENGTH = 'INVALID_LENGTH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: live_boundary_patch.py:101
    INVALID_MAPPING = 'INVALID_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: mapping_provenance.py:34, mapping_provenance.py:45, mapping_provenance.py:52 ...
    INVALID_MAPPING_RECORD = 'INVALID_MAPPING_RECORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:28, test_metadata_verification.py:29, metadata_verification.py:22 ...
    INVALID_METADATA_RECORD = 'INVALID_METADATA_RECORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:61
    INVALID_NONCE = 'INVALID_NONCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:36, episode_reconciliation.py:49
    INVALID_NUMBER = 'INVALID_NUMBER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:60
    INVALID_OR_CONFLICTING_EPISODE_NUMBER = 'INVALID_OR_CONFLICTING_EPISODE_NUMBER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:100, autobrr_discovery_inbox.py:111, approval_authorization.py:55 ...
    INVALID_PAYLOAD = 'INVALID_PAYLOAD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:80
    INVALID_PIN_CONTEXT = 'INVALID_PIN_CONTEXT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:46
    INVALID_PREFIX = 'INVALID_PREFIX'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1112, api.py:1195, api.guarded.candidate.py:1126 ...
    INVALID_PROBE_OUTPUT = 'INVALID_PROBE_OUTPUT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:62
    INVALID_PROVIDER = 'INVALID_PROVIDER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:39
    INVALID_PROVIDER_PATH = 'INVALID_PROVIDER_PATH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:55
    INVALID_RECORDS = 'INVALID_RECORDS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:38, release_catalog_gate.py:27
    INVALID_RELEASE_NAME = 'INVALID_RELEASE_NAME'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:80
    INVALID_REQUEST = 'INVALID_REQUEST'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:26
    INVALID_RESPONSE_SIZE = 'INVALID_RESPONSE_SIZE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_gateway.py:20
    INVALID_REVISION = 'INVALID_REVISION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: transactional_approval.py:66
    INVALID_REVISION_ID = 'INVALID_REVISION_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:68, metadata_verification.py:15
    INVALID_SERIES_ID = 'INVALID_SERIES_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:87, approval_authorization.py:90
    INVALID_SIGNATURE = 'INVALID_SIGNATURE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:59, trusted_evidence.py:68
    INVALID_SNAPSHOT = 'INVALID_SNAPSHOT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:66, approval_authorization.py:68, approval_authorization.py:71
    INVALID_TARGET = 'INVALID_TARGET'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_gateway.py:22
    INVALID_TIME = 'INVALID_TIME'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:63
    INVALID_TIME_WINDOW = 'INVALID_TIME_WINDOW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:97
    INVALID_TRIAL_LIMIT = 'INVALID_TRIAL_LIMIT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:55
    INVALID_TVDB_ID = 'INVALID_TVDB_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:90
    INVALID_TVMAZE_EPISODES = 'INVALID_TVMAZE_EPISODES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:87
    INVALID_TVMAZE_ID = 'INVALID_TVMAZE_ID'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:79
    INVALID_TVMAZE_SHOW = 'INVALID_TVMAZE_SHOW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1230, api.guarded.candidate.py:1244, api.candidate.py:1224
    JAPANESE_AUDIO_MISSING = 'JAPANESE_AUDIO_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:92
    JSON_REQUIRED = 'JSON_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_mapping_v4.py:21, anime_identity_crosscheck_v3.py:33, anime_identity_crosscheck_v3.py:66 ...
    LIVE_ACTION = 'LIVE_ACTION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trial_integration_sprint.py:119
    MANUAL_APPROVED = 'MANUAL_APPROVED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_audit_v5.py:54
    MAPPED_EPISODE_OUT_OF_RANGE = 'MAPPED_EPISODE_OUT_OF_RANGE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:27
    MAPPING_AUDIT_CONFLICT = 'MAPPING_AUDIT_CONFLICT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:23
    MAPPING_AUDIT_DISAGREES = 'MAPPING_AUDIT_DISAGREES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_mapping_v4.py:22
    MAPPING_CONFLICT = 'MAPPING_CONFLICT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:111
    MAPPING_ENTRIES_MISMATCH = 'MAPPING_ENTRIES_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: mapping_provenance.py:60, test_mapping_provenance.py:55, test_mapping_provenance.py:89
    MAPPING_NOT_APPROVED = 'MAPPING_NOT_APPROVED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:29, test_episode_reconciliation.py:30, test_episode_reconciliation.py:47 ...
    MAPPING_NOT_FOUND = 'MAPPING_NOT_FOUND'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: mapping_provenance.py:56, test_mapping_provenance.py:49
    MAPPING_SERIES_MISMATCH = 'MAPPING_SERIES_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:21, test_metadata_verification.py:22, metadata_verification.py:24
    METADATA_NOT_VERIFIED = 'METADATA_NOT_VERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:26, metadata_verification.py:32
    METADATA_SEASON_MISMATCH = 'METADATA_SEASON_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:25, test_metadata_verification.py:34, metadata_verification.py:30
    METADATA_SERIES_MISMATCH = 'METADATA_SERIES_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:27, test_metadata_verification.py:35, metadata_verification.py:37
    METADATA_TITLE_MISMATCH = 'METADATA_TITLE_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:35, test_anilist_adapter.py:36, anilist_adapter.py:27
    MISSING_EPISODE_COUNT = 'MISSING_EPISODE_COUNT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:66, episode_reconciliation.py:88
    MISSING_EPISODE_EVIDENCE = 'MISSING_EPISODE_EVIDENCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_mapping.py:80, test_metadata_verification.py:30, test_canonical_mapping.py:26
    MISSING_EPISODE_MAPPING = 'MISSING_EPISODE_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: production_readiness_audit.py:43
    MISSING_FUNCTION = 'MISSING_FUNCTION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:57
    MISSING_OFFSET_TREATED_AS_UNPROVEN_ZERO_HYPOTHESIS = 'MISSING_OFFSET_TREATED_AS_UNPROVEN_ZERO_HYPOTHESIS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_identity.py:180
    MISSING_OR_AMBIGUOUS_EPISODE = 'MISSING_OR_AMBIGUOUS_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:40
    MISSING_SOURCES = 'MISSING_SOURCES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:34, anilist_adapter.py:24
    MISSING_TITLE = 'MISSING_TITLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: series_identity.py:68
    MISSING_TRUSTED_TITLE = 'MISSING_TRUSTED_TITLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_identity.py:155, release_identity.py:159, release_identity.py:169
    MULTIPLE_EPISODE_IDENTIFIERS = 'MULTIPLE_EPISODE_IDENTIFIERS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:35
    MULTIPLE_OR_MISSING_MAPPING_RECORDS = 'MULTIPLE_OR_MISSING_MAPPING_RECORDS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:31
    MULTI_EPISODE = 'MULTI_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:28
    MULTI_EPISODE_RELEASE = 'MULTI_EPISODE_RELEASE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_audit.py:65, controller_integration_audit.py:66, controller_integration_audit.py:67
    NEEDS_MANUAL_CODE_REVIEW = 'NEEDS_MANUAL_CODE_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:231, api.py:228, api.py:229 ...
    NEEDS_REVIEW = 'NEEDS_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:59, anilist_adapter.py:62
    NETWORK_OR_RESPONSE_ERROR = 'NETWORK_OR_RESPONSE_ERROR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_worker_v10.py:17, anime_identity_worker_v10.py:52, anime_identity_worker_v11.py:46
    NEW_IDENTITY_LOOKUP_PENDING_RATE_LIMIT_INTEGRATION = 'NEW_IDENTITY_LOOKUP_PENDING_RATE_LIMIT_INTEGRATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:135
    NONCONTIGUOUS_OR_CONFLICTING_PREFIX = 'NONCONTIGUOUS_OR_CONFLICTING_PREFIX'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:116
    NONREGULAR_TVMAZE_EPISODE = 'NONREGULAR_TVMAZE_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:50
    NONZERO_OFFSET_REQUIRES_EXPLICIT_MAPPING = 'NONZERO_OFFSET_REQUIRES_EXPLICIT_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:51, test_episode_reconciliation.py:65
    NON_REGULAR = 'NON_REGULAR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:107
    NON_REGULAR_EPISODE = 'NON_REGULAR_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:42
    NON_STANDARD_TVDB_SEASON = 'NON_STANDARD_TVDB_SEASON'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:20
    NON_UNIQUE_SERIES_MAPPING_OR_AUDIT = 'NON_UNIQUE_SERIES_MAPPING_OR_AUDIT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:45
    NORMALIZED_EPISODES_REQUIRED = 'NORMALIZED_EPISODES_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_audit.py:69, controller_integration_audit.py:70
    NOT_CONNECTED_TO_LIVE_API = 'NOT_CONNECTED_TO_LIVE_API'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1507, api.guarded.candidate.py:1521, api.candidate.py:1501
    NOT_ELIGIBLE = 'NOT_ELIGIBLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: production_readiness_audit.py:24
    NOT_ENFORCED_GLOBALLY = 'NOT_ENFORCED_GLOBALLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:90, test_identity_episode_v6.py:14
    NOT_FOUND = 'NOT_FOUND'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: production_readiness_audit.py:22, production_readiness_audit.py:23, production_readiness_audit.py:25 ...
    NOT_IMPLEMENTED = 'NOT_IMPLEMENTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_audit.py:68
    NOT_IMPLEMENTED_IN_PROTOTYPE = 'NOT_IMPLEMENTED_IN_PROTOTYPE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: production_readiness_audit.py:28
    NOT_INTEGRATED = 'NOT_INTEGRATED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1402, api.guarded.candidate.py:1416, api.candidate.py:1396
    NOT_IN_STAGED_STATE = 'NOT_IN_STAGED_STATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1279, api.py:1348, api.py:1421 ...
    NOT_READABLE = 'NOT_READABLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:840, api.py:1265, api.py:1337 ...
    NOT_REGULAR_FILE = 'NOT_REGULAR_FILE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_audit.py:71
    NOT_REHEARSED_ON_PRODUCTION_COPY = 'NOT_REHEARSED_ON_PRODUCTION_COPY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: production_readiness_audit.py:29
    NOT_REVIEWED = 'NOT_REVIEWED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:989, api.guarded.candidate.py:1003, api.candidate.py:983
    NOT_STAGED = 'NOT_STAGED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_audit.py:58
    NOT_VERIFIED = 'NOT_VERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: transactional_approval.py:76
    NO_ACTIVE_PENDING_REVISION = 'NO_ACTIVE_PENDING_REVISION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:790, api.guarded.candidate.py:804, api.candidate.py:784
    NO_ATTEMPTS_REGISTERED = 'NO_ATTEMPTS_REGISTERED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1133, api.guarded.candidate.py:1147, api.candidate.py:1127
    NO_AUDIO_STREAM = 'NO_AUDIO_STREAM'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v9.py:43, test_identity_worker_v9.py:18
    NO_RUNNER_CONFIGURED = 'NO_RUNNER_CONFIGURED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:127
    NO_SEASON_ONE_DATA = 'NO_SEASON_ONE_DATA'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:822, api.guarded.candidate.py:836, api.candidate.py:816
    NO_STABILITY_OBSERVATION = 'NO_STABILITY_OBSERVATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:20, metadata_verification.py:19
    NO_TRUSTED_METADATA = 'NO_TRUSTED_METADATA'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1130, api.guarded.candidate.py:1144, api.candidate.py:1124
    NO_VIDEO_STREAM = 'NO_VIDEO_STREAM'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:78, test_metadata_provenance_gate.py:21
    NUMBERING_CONFLICT = 'NUMBERING_CONFLICT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_mapping.py:70, test_canonical_mapping.py:33, test_canonical_mapping.py:40
    OUTSIDE_CANONICAL_TRIAL = 'OUTSIDE_CANONICAL_TRIAL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:832, api.py:1259, api.py:1440 ...
    OUTSIDE_STAGING_ROOT = 'OUTSIDE_STAGING_ROOT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_identity.py:191
    OUTSIDE_TRIAL_EPISODES = 'OUTSIDE_TRIAL_EPISODES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1332, api.guarded.candidate.py:1346, api.candidate.py:1326
    OUTSIDE_TRIAL_LIBRARY = 'OUTSIDE_TRIAL_LIBRARY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:928, api.guarded.candidate.py:942, api.candidate.py:922
    OUTSIDE_TRIAL_LIMIT = 'OUTSIDE_TRIAL_LIMIT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:52, test_episode_reconciliation.py:56, episode_reconciliation.py:115 ...
    OUTSIDE_TRIAL_WINDOW = 'OUTSIDE_TRIAL_WINDOW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: live_boundary_patch.py:45, live_boundary_patch.py:164
    O_NOFOLLOW = 'O_NOFOLLOW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: live_boundary_patch.py:45, live_boundary_patch.py:165
    O_NONBLOCK = 'O_NONBLOCK'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1284, api.py:1443, api.guarded.candidate.py:1298 ...
    PATH_RESOLUTION_FAILED = 'PATH_RESOLUTION_FAILED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trial_integration_sprint.py:116, api.py:230, api.py:228 ...
    PENDING_REVIEW = 'PENDING_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:939, api.guarded.candidate.py:953, test_import_continuity.py:112 ...
    PREVIOUS_EPISODE_MISSING = 'PREVIOUS_EPISODE_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_deployment_safety_pass2.py:29, test_deployment_safety_pass2.py:33
    PRODUCTION_DB = 'PRODUCTION_DB'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: deployment_candidate.py:27
    PRODUCTION_SNAPSHOT_RESTORE_NOT_VERIFIED = 'PRODUCTION_SNAPSHOT_RESTORE_NOT_VERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: auth_evidence_boundary.py:37
    PRODUCTION_TRUSTED_METADATA_GATEWAY_NOT_IMPLEMENTED = 'PRODUCTION_TRUSTED_METADATA_GATEWAY_NOT_IMPLEMENTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:87, test_metadata_provenance_gate.py:34
    PRODUCTION_TRUST_GATE_NOT_IMPLEMENTED = 'PRODUCTION_TRUST_GATE_NOT_IMPLEMENTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: deployment_candidate.py:25
    PROVENANCE_ADAPTER_UNVERIFIED = 'PROVENANCE_ADAPTER_UNVERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:46
    PROVIDER_HTTP_ERROR = 'PROVIDER_HTTP_ERROR'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:44
    PROVIDER_REDIRECT_BLOCKED = 'PROVIDER_REDIRECT_BLOCKED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:70, test_canonical_provider_integration.py:55
    PROVIDER_REDIRECT_OR_STATUS = 'PROVIDER_REDIRECT_OR_STATUS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:51
    PROVIDER_UNAVAILABLE = 'PROVIDER_UNAVAILABLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: deployment_candidate.py:26
    QBITTORRENT_MUTATION_WORKER_NOT_DEPLOYED = 'QBITTORRENT_MUTATION_WORKER_NOT_DEPLOYED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_anime_service_connections.py:9, ownership_audit.py:69
    QBITTORRENT_PASSWORD = 'QBITTORRENT_PASSWORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_anime_service_connections.py:10, ownership_audit.py:70
    QBITTORRENT_URL = 'QBITTORRENT_URL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_anime_service_connections.py:8, ownership_audit.py:68
    QBITTORRENT_USERNAME = 'QBITTORRENT_USERNAME'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v12.py:58, anime_identity_worker_v15.py:78, test_identity_worker_v12.py:18 ...
    RATE_LIMITED_RETRY = 'RATE_LIMITED_RETRY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v9.py:28
    READ_ONLY = 'READ_ONLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_plan.py:46
    READ_REQUIRES_ACCESS_REVIEW = 'READ_REQUIRES_ACCESS_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_worker.py:115, test_cancellation_worker.py:49, test_cancellation_worker.py:53
    RECORDED_SIMULATION = 'RECORDED_SIMULATION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_attempt_evidence_fencing.py:18, attempt_evidence_fencing.py:93
    RECORDED_SIMULATION_ONLY = 'RECORDED_SIMULATION_ONLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:73, test_canonical_provider_integration.py:61
    REDIRECT_SHOW_ID_MISMATCH = 'REDIRECT_SHOW_ID_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:68
    RELEASE_FILE_EPISODE_MISMATCH = 'RELEASE_FILE_EPISODE_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:72
    RELEASE_NAME_MISSING = 'RELEASE_NAME_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_production_edges.py:34, production_edges.py:105
    REMOVE_REQUESTED = 'REMOVE_REQUESTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:98
    REPLAYED_NONCE = 'REPLAYED_NONCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:15
    RETRY_OR_REVIEW = 'RETRY_OR_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v15.py:60, anime_identity_worker_v11.py:60, anime_identity_worker_v9.py:53 ...
    RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE = 'RETRY_OR_REVIEW_CANDIDATE_NO_STATUS_CHANGE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_verification_v16.py:22
    REVIEW_REQUIRED = 'REVIEW_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:105
    REVISION_CHANGED = 'REVISION_CHANGED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:87
    REVISION_MISMATCH = 'REVISION_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:15
    REVOKE_IDENTITY = 'REVOKE_IDENTITY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: auth_evidence_boundary.py:57, auth_evidence_boundary.py:64, approval_authorization.py:15 ...
    REVOKE_MAPPING = 'REVOKE_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: dashboard.py:412
    SCAN_PENDING = 'SCAN_PENDING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:30
    SCHEMA_MISMATCH = 'SCHEMA_MISMATCH'
    #: Meaning: Series identity was saved, but episode verification remains pending.
    #: Produced by / cause: Identity queue action/state.
    #: Effect: Must be eligible for reconciliation if no verification row exists.
    #: Debug: Inspect queue record and episode_verification_v16 table.
    #: Seen at: anime_identity_worker_v12.py:16, anime_identity_worker_v15.py:19, anime_identity_worker_v15.py:48 ...
    SERIES_ALREADY_PERSISTED_EPISODE_PENDING = 'SERIES_ALREADY_PERSISTED_EPISODE_PENDING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:86, metadata_provenance_gate.py:75, test_metadata_provenance_gate.py:22
    SERIES_ID_MISMATCH = 'SERIES_ID_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:56
    SERIES_LABEL_MISSING = 'SERIES_LABEL_MISSING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:19
    SERIES_MAPPING_NOT_UNIQUE = 'SERIES_MAPPING_NOT_UNIQUE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_canonical_catalogs.py:18
    SERIES_NOT_FOUND = 'SERIES_NOT_FOUND'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_series_identity.py:18, test_series_identity.py:39, series_identity.py:84 ...
    SERIES_TITLE_MISMATCH = 'SERIES_TITLE_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_persistence_v8.py:9, anime_identity_persistence_v8.py:32, anime_identity_decision_v7.py:37 ...
    SERIES_VERIFIED_EPISODE_PENDING = 'SERIES_VERIFIED_EPISODE_PENDING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:83, test_identity_confidence_v14.py:28, anime_identity_confidence_v14.py:52 ...
    SHADOW_BLOCKED = 'SHADOW_BLOCKED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_confidence_v14.py:38, anime_identity_confidence_v14.py:50
    SHADOW_DISABLED = 'SHADOW_DISABLED'
    #: Meaning: Shadow evaluator has high confidence by its scoring policy.
    #: Produced by / cause: V13 scoring and blocker check.
    #: Effect: Not itself an approval or acquisition authorization.
    #: Debug: Inspect verification evidence separately.
    #: Seen at: anime_episode_verification_v16.py:11, anime_episode_confidence_v13.py:83, test_identity_confidence_v14.py:22 ...
    SHADOW_HIGH_CONFIDENCE = 'SHADOW_HIGH_CONFIDENCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v15.py:71
    SHADOW_MANUAL = 'SHADOW_MANUAL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:83, anime_identity_confidence_v14.py:58, test_episode_verification_v16.py:31
    SHADOW_MORE_EVIDENCE = 'SHADOW_MORE_EVIDENCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:81, anime_identity_confidence_v14.py:59
    SHADOW_ONLY = 'SHADOW_ONLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_confidence_v14.py:56
    SHADOW_REVIEW_CANDIDATE = 'SHADOW_REVIEW_CANDIDATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v15.py:71
    SHADOW_WATCH = 'SHADOW_WATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_controller_integration_audit.py:26
    SHOULD_NOT_LEAK = 'SHOULD_NOT_LEAK'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:63, anime_identity_confidence_v14.py:46
    SINGLE_EPISODE_NUMBER_PARSED = 'SINGLE_EPISODE_NUMBER_PARSED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_worker_v9.py:35, test_identity_worker_v9.py:17
    SKIPPED_NON_UNTRUSTED = 'SKIPPED_NON_UNTRUSTED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:66
    SNAPSHOT_CONFLICT = 'SNAPSHOT_CONFLICT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:114
    SNAPSHOT_STALE = 'SNAPSHOT_STALE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_anime_service_connections.py:15, check_canonical_catalogs.py:9, pilot_readiness.py:110
    SONARR_API_KEY = 'SONARR_API_KEY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_anime_service_connections.py:20
    SONARR_CA_BUNDLE = 'SONARR_CA_BUNDLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: identity_evidence_assembly.py:37
    SONARR_IDENTITY_MISMATCH = 'SONARR_IDENTITY_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:99
    SONARR_TVDB_ID_REQUIRED = 'SONARR_TVDB_ID_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: check_anime_service_connections.py:19
    SONARR_URL = 'SONARR_URL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:83
    SOURCE_AUTHENTICITY_NOT_ESTABLISHED = 'SOURCE_AUTHENTICITY_NOT_ESTABLISHED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:49, episode_reconciliation.py:113
    SOURCE_MAPPING_CONFLICT = 'SOURCE_MAPPING_CONFLICT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:36
    SOURCE_NOT_ALLOWED = 'SOURCE_NOT_ALLOWED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:42
    SOURCE_UNAVAILABLE = 'SOURCE_UNAVAILABLE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_series_identity.py:60, release_identity.py:120
    SPECIAL_OR_NON_EPISODE = 'SPECIAL_OR_NON_EPISODE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:24
    SPECIAL_RELEASE = 'SPECIAL_RELEASE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:74
    SPECIAL_SEQUEL_BATCH_OR_MULTI_EPISODE_RELEASE = 'SPECIAL_SEQUEL_BATCH_OR_MULTI_EPISODE_RELEASE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:870, api.guarded.candidate.py:884, api.candidate.py:864
    STABILITY_WINDOW_INCOMPLETE = 'STABILITY_WINDOW_INCOMPLETE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_attempt_identity.py:87, api.py:1007, api.guarded.candidate.py:1021 ...
    STAGED_ATTEMPT_MISMATCH = 'STAGED_ATTEMPT_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:81, test_metadata_provenance_gate.py:26, test_metadata_provenance_gate.py:29
    STALE_OR_FUTURE_RECORD = 'STALE_OR_FUTURE_RECORD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:52
    SYMLINK_DATABASE_FORBIDDEN = 'SYMLINK_DATABASE_FORBIDDEN'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_controller_evidence_v8.py:28, anime_identity_verify.py:81
    TITLE_CORROBORATED_REVIEW_REQUIRED = 'TITLE_CORROBORATED_REVIEW_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: autobrr_discovery_inbox.py:76
    TOKEN_TOO_SHORT = 'TOKEN_TOO_SHORT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: source_provenance.py:134
    TRANSPORT_OBSERVED_NOT_CROSS_VERIFIED = 'TRANSPORT_OBSERVED_NOT_CROSS_VERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_mapping.py:86, test_mapping_provenance.py:42, test_canonical_mapping.py:12 ...
    TRUSTED_CANONICAL_MAPPING = 'TRUSTED_CANONICAL_MAPPING'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_series_identity.py:11, test_series_identity.py:25, test_series_identity.py:32 ...
    TRUSTED_TITLE_MATCH = 'TRUSTED_TITLE_MATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:82, test_canonical_provider_integration.py:64
    TVDB_CROSS_REFERENCE_MISMATCH = 'TVDB_CROSS_REFERENCE_MISMATCH'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_audit_v5.py:25
    TVDB_EPISODE_EXISTENCE = 'TVDB_EPISODE_EXISTENCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_identity_decision_v7.py:19, anime_identity_decision_v7.py:30
    TVDB_EPISODE_NOT_CONFIRMED = 'TVDB_EPISODE_NOT_CONFIRMED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:66
    TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED = 'TVDB_EPISODE_NOT_UNIQUELY_CONFIRMED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:69, anime_identity_confidence_v14.py:47
    TVDB_SEASON_ONE_EPISODE_RECORD_EXISTS = 'TVDB_SEASON_ONE_EPISODE_RECORD_EXISTS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: canonical_provider_integration.py:77
    TVMAZE_LOOKUP_FAILED = 'TVMAZE_LOOKUP_FAILED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anilist_adapter.py:30
    TV_SHORT = 'TV_SHORT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: live_boundary_patch.py:115
    TWO_INDEPENDENT_AUTHORITIES = 'TWO_INDEPENDENT_AUTHORITIES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:55
    TWO_SNAPSHOTS_REQUIRED = 'TWO_SNAPSHOTS_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:41
    TWO_SOURCES = 'TWO_SOURCES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: trusted_evidence.py:70, episode_reconciliation.py:74
    TWO_SOURCES_REQUIRED = 'TWO_SOURCES_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: metadata_provenance_gate.py:60, test_metadata_provenance_gate.py:19
    TWO_SOURCE_RECORDS_REQUIRED = 'TWO_SOURCE_RECORDS_REQUIRED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:39
    UNRECOGNIZED_MAPPING_FLAGS = 'UNRECOGNIZED_MAPPING_FLAGS'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:1252, api.py:1325, api.py:1408 ...
    UNSUPPORTED_EXTENSION = 'UNSUPPORTED_EXTENSION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_catalog_gate.py:64
    UNSUPPORTED_FILE_EXTENSION = 'UNSUPPORTED_FILE_EXTENSION'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_anilist_adapter.py:39, test_anilist_adapter.py:40, anilist_adapter.py:31
    UNSUPPORTED_FORMAT = 'UNSUPPORTED_FORMAT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:23, test_metadata_verification.py:24, metadata_verification.py:26
    UNSUPPORTED_METADATA_SOURCE = 'UNSUPPORTED_METADATA_SOURCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_series_identity.py:67, series_identity.py:64
    UNSUPPORTED_RELEASE_FORMAT = 'UNSUPPORTED_RELEASE_FORMAT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_episode_reconciliation.py:37
    UNSUPPORTED_SEASON = 'UNSUPPORTED_SEASON'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: episode_reconciliation.py:26, episode_reconciliation.py:46
    UNSUPPORTED_SEASON_MARKER = 'UNSUPPORTED_SEASON_MARKER'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: mapping_provenance.py:66, test_mapping_provenance.py:61, test_mapping_provenance.py:67
    UNTRUSTED_APPROVAL_SOURCE = 'UNTRUSTED_APPROVAL_SOURCE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_episode_confidence_v13.py:18
    UPSTREAM_ISSUES = 'UPSTREAM_ISSUES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_identity_decision_v7.py:17
    UPSTREAM_LOOKUP_ISSUES = 'UPSTREAM_LOOKUP_ISSUES'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: dashboard.py:338, dashboard.py:345, test_controller_identity_v7.py:24
    USER_PROVIDED_UNVERIFIED = 'USER_PROVIDED_UNVERIFIED'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_metadata_verification.py:19, test_metadata_verification.py:13, metadata_verification.py:43
    VERIFIED_MAPPING_CANDIDATE = 'VERIFIED_MAPPING_CANDIDATE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:784, api.guarded.candidate.py:798, api.candidate.py:778
    VERIFY_AND_IMPORT = 'VERIFY_AND_IMPORT'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: api.py:786, api.guarded.candidate.py:800, api.candidate.py:780
    WAIT_FOR_DOWNLOAD = 'WAIT_FOR_DOWNLOAD'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: approval_authorization.py:46, approval_authorization.py:81
    WEAK_ADMIN_KEY = 'WEAK_ADMIN_KEY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: cancellation_worker.py:79, test_cancellation_worker.py:25, test_cancellation_worker.py:27 ...
    WOULD_CANCEL = 'WOULD_CANCEL'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: anime_discovery_review_worker.py:56
    WOULD_NEED_REVIEW = 'WOULD_NEED_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_cancellation_preflight.py:22, test_cancellation_preflight.py:30, test_cancellation_preflight.py:70 ...
    WOULD_REMOVE_TORRENT_ONLY = 'WOULD_REMOVE_TORRENT_ONLY'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: deployment_candidate.py:78, test_deployment_candidate.py:41
    WOULD_REMOVE_WITH_DELETE_FILES_FALSE = 'WOULD_REMOVE_WITH_DELETE_FILES_FALSE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: test_attempt_evidence_fencing.py:56, attempt_evidence_fencing.py:112
    WOULD_REQUEST_REMOVE_WITH_DELETE_FILES_FALSE = 'WOULD_REQUEST_REMOVE_WITH_DELETE_FILES_FALSE'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: controller_integration_plan.py:46, test_controller_integration_plan.py:60
    WRITE_REQUIRES_AUTH_REVIEW = 'WRITE_REQUIRES_AUTH_REVIEW'
    #: Not yet semantically reviewed; this is a literal code found in the source.
    #: Seen at: release_identity.py:187, release_identity.py:138, test_release_identity.py:71 ...
    WRONG_SEASON = 'WRONG_SEASON'
