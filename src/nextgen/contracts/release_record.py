"""Anime Discovery ReleaseRecord v1 — canonical, immutable stage-enriched contract.

One schema from webhook intake to explicit Keep/Reject and Sonarr export.
This module has no database, network, daemon or filesystem side effects.

Field metadata is machine-checkable documentation: meaning, reason, owner,
availability and trust. v1 keeps absent stage results as None; it never
infers missing TVDB mappings, paths, media verification or user decisions.
"""
from dataclasses import dataclass, field, fields, asdict
from typing import Optional
import json

SCHEMA_VERSION = 1

def documented(*, meaning, reason, owner, available, trust):
    return field(metadata=dict(meaning=meaning, reason=reason, owner=owner,
                               available=available, trust=trust))

def optional(*, meaning, reason, owner, available, trust):
    return field(default=None, metadata=dict(meaning=meaning, reason=reason,
                        owner=owner, available=available, trust=trust))

def positive(value, label):
    if type(value) is not int or value < 1:
        raise ValueError(label + " must be a positive integer")

@dataclass(frozen=True)
class Intake:
    """Immutable notification facts, never treated as verification evidence."""
    notification_id: int = documented(meaning="Durable notification row ID",reason="Correlates release and permanent history",owner="intake",available="receipt",trust="database-key")
    source: str = documented(meaning="Webhook origin",reason="Identify notification producer",owner="intake",available="receipt",trust="untrusted-origin")
    source_guid: str = documented(meaning="Original provider event GUID",reason="Deduplicate source events",owner="intake",available="receipt",trust="untrusted")
    release_name: str = documented(meaning="Original supplied release label",reason="Human audit and identity lookup hint",owner="intake",available="receipt",trust="untrusted")
    info_hash: str = documented(meaning="Received torrent info hash",reason="Correlate acquisition and ownership checks",owner="intake",available="receipt",trust="untrusted")
    received_at: int = documented(meaning="Receipt Unix timestamp",reason="Ordering and historical context",owner="intake",available="receipt",trust="database-recorded")

    def __post_init__(self):
        positive(self.notification_id,"notification_id")
        if type(self.received_at) is not int or self.received_at < 0:
            raise ValueError("received_at must be a nonnegative Unix timestamp")
        for key in ("source","source_guid","release_name","info_hash"):
            v=getattr(self,key)
            if not isinstance(v,str) or not v:
                raise ValueError(key+" must be nonempty text")

@dataclass(frozen=True)
class Identity:
    """Only the identity component may publish verified identity results."""
    anidb_id: int = documented(meaning="Verified AniDB anime ID",reason="Canonical anime identity",owner="identity",available="verified-identity",trust="verified")
    tvdb_id: int = documented(meaning="Verified TVDB series ID",reason="Existing staging NFO and Sonarr compatibility",owner="identity",available="verified-identity",trust="verified")
    season: int = documented(meaning="Verified TVDB season number",reason="Avoid wrong sequel/cour staging",owner="identity",available="verified-identity",trust="verified")
    episode: int = documented(meaning="Verified TVDB episode number",reason="Exact staging and import destination",owner="identity",available="verified-identity",trust="verified")
    mapping_source: str = documented(meaning="Cross-provider episode mapping provenance code",reason="Audit proof without guessing numbering",owner="identity",available="verified-identity",trust="verified-provenance")

    def __post_init__(self):
        for name in ("anidb_id","tvdb_id","episode"):
            positive(getattr(self,name),name)
        if type(self.season) is not int or self.season < 0:
            raise ValueError("season must be a nonnegative integer")
        if not isinstance(self.mapping_source,str) or not self.mapping_source:
            raise ValueError("mapping_source required")

@dataclass(frozen=True)
class Acquisition:
    """Durable, independently checked acquisition result."""
    job_id: int = documented(meaning="Acquisition job row ID",reason="Trace job retry and ownership",owner="acquisition",available="acquisition",trust="database-key")
    ownership_verified: bool = documented(meaning="Torrent belongs to this acquisition",reason="Prevent deletion or reuse of unrelated torrents",owner="acquisition",available="acquisition",trust="verified")
    media_verified: bool = documented(meaning="Media passed configured safety checks",reason="Preserve audio and size safeguards",owner="acquisition",available="acquisition",trust="verified")

    def __post_init__(self):
        positive(self.job_id,"job_id")
        if type(self.ownership_verified) is not bool or type(self.media_verified) is not bool:
            raise ValueError("verification flags must be boolean")

@dataclass(frozen=True)
class Staging:
    """Staging outcome; path is evidence, never permission to trust a path."""
    staged_path: str = documented(meaning="Published staged media location",reason="Locate Jellyfin evaluation media",owner="staging",available="staged",trust="must-revalidate-at-use")
    nfo_written: bool = documented(meaning="Jellyfin NFO metadata was written",reason="Verify integration output",owner="staging",available="staged",trust="component-verified")

    def __post_init__(self):
        if not isinstance(self.staged_path,str) or not self.staged_path:
            raise ValueError("staged_path required")
        if type(self.nfo_written) is not bool:
            raise ValueError("nfo_written must be boolean")

@dataclass(frozen=True)
class Evaluation:
    """Human review; Keep is never implied by reaching staging."""
    decision: str = documented(meaning="Explicit human decision KEEP or REJECT",reason="Keep/Reject safety boundary",owner="evaluation",available="human-review",trust="human-authorized")

    def __post_init__(self):
        if self.decision not in ("KEEP","REJECT"):
            raise ValueError("decision must be KEEP or REJECT")

@dataclass(frozen=True)
class Export:
    """Sonarr export result, not an import authorization on its own."""
    result: str = documented(meaning="Result of explicit Sonarr export attempt",reason="Keep export audit trail",owner="sonarr-export",available="export",trust="component-observed")

    def __post_init__(self):
        if not isinstance(self.result,str) or not self.result:
            raise ValueError("export result required")

@dataclass(frozen=True)
class ReleaseRecord:
    """Canonical release lifecycle record, schema version 1.

    A single immutable snapshot shape whose optional sections are populated
    progressively. The durable tables remain authoritative; this is a
    transport/read-model contract, not a second job database.
    """
    schema_version: int = documented(meaning="Canonical contract major version",reason="Reject incompatible stored or transmitted shapes",owner="infrastructure",available="always",trust="contract")
    trace_id: str = documented(meaning="Stable release correlation identifier",reason="Follow activity across independent jobs",owner="infrastructure",available="receipt",trust="derived")
    intake: Intake = documented(meaning="Notification receipt facts",reason="Preserve original release context",owner="intake",available="receipt",trust="mixed-untrusted")
    identity: Optional[Identity] = optional(meaning="Verified AniDB/TVDB episode mapping",reason="Required before existing acquisition and NFO staging",owner="identity",available="after-verification",trust="verified")
    acquisition: Optional[Acquisition] = optional(meaning="Acquisition/media evidence",reason="Track acquisition safety outcome",owner="acquisition",available="after-acquisition",trust="component-verified")
    staging: Optional[Staging] = optional(meaning="Staged file and NFO outcome",reason="Enable safe Jellyfin review",owner="staging",available="after-staging",trust="must-revalidate-path")
    evaluation: Optional[Evaluation] = optional(meaning="Explicit human evaluation result",reason="Keep/Reject gating",owner="evaluation",available="after-review",trust="human-authorized")
    export: Optional[Export] = optional(meaning="Sonarr import attempt result",reason="Record post-Keep export",owner="sonarr-export",available="after-keep",trust="component-observed")

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version != SCHEMA_VERSION:
            raise ValueError("Unsupported ReleaseRecord schema version")
        if self.trace_id != "AD-"+str(self.intake.notification_id):
            raise ValueError("Trace ID does not match notification")
        for name, klass in (("identity",Identity),("acquisition",Acquisition),
                            ("staging",Staging),("evaluation",Evaluation),("export",Export)):
            value=getattr(self,name)
            if value is not None and not isinstance(value,klass):
                raise ValueError(name+" must have the declared type")
        if self.acquisition is not None and self.identity is None:
            raise ValueError("Acquisition requires verified identity")
        if self.staging is not None and (self.identity is None or self.acquisition is None
                                         or not self.acquisition.media_verified):
            raise ValueError("Staging requires verified identity and media")
        if self.evaluation is not None and self.staging is None:
            raise ValueError("Evaluation requires staging")
        if self.export is not None and (self.evaluation is None or self.evaluation.decision!="KEEP"
                                        or self.identity is None):
            raise ValueError("Sonarr export requires explicit Keep and verified identity")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data):
        """Reject unknown fields and non-v1 records instead of guessing."""
        if not isinstance(data,dict):
            raise ValueError("ReleaseRecord must be an object")
        def parse(typ, value):
            if not isinstance(value,dict):
                raise ValueError(typ.__name__+" must be an object")
            expected={f.name for f in fields(typ)}
            if set(value) != expected:
                raise ValueError("Invalid "+typ.__name__+" fields")
            return typ(**value)
        expected={f.name for f in fields(cls)}
        if not {"schema_version","trace_id","intake"}.issubset(data) or set(data)-expected:
            raise ValueError("Missing required or unknown ReleaseRecord fields")
        values=dict(data)
        values["intake"]=parse(Intake,values["intake"])
        for name,typ in (("identity",Identity),("acquisition",Acquisition),
                         ("staging",Staging),("evaluation",Evaluation),("export",Export)):
            if values.get(name) is not None:
                values[name]=parse(typ,values[name])
        return cls(**values)

    @classmethod
    def from_json(cls, text):
        return cls.from_dict(json.loads(text))

    def to_json(self):
        return json.dumps(self.to_dict(),sort_keys=True)
