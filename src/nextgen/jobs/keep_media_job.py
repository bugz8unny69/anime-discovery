"""Keep a single approved staged episode through Sonarr, never direct moves.

The command is submitted only in the attempt that atomically created its
IMPORT_INTENT. A worker restart, lost HTTP response or expired lease cannot
silently authorize repeating a ManualImport command. Trial files are preserved.
"""
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import CompletionRejected, Outcome, Registration
from src.nextgen.secrets import SecretStorageError
from src.nextgen.sonarr import SonarrClient, SonarrOptions, SonarrReview, SonarrUnavailable
from src.nextgen.keep_files import KeepFileReview, staged, verified_library
from src.nextgen.storage.keep import KeepJournal, KeepReview
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable

KIND = "KEEP_MEDIA"
DEFINITION = HandlerDefinition(KIND, "Keep one approved episode through Sonarr")


def _persist(db, claim, value):
    if type(value) is not dict:
        raise CompletionRejected(Outcome("review", "KEEP_FILE_REVIEW"))
    try:
        # Runs in the SAME lease-fenced transaction as jobs.DONE.
        KeepJournal("").verified(db,claim,value)
    except (KeepReview,ValueError,TypeError,KeyError):
        raise CompletionRejected(Outcome("review", "KEEP_FILE_REVIEW")) from None


def _options(row,configuration,key):
    if row["phase"]=="APPROVED":
        root=configuration.value("storage.keep_root")
        sonarr_root=configuration.value("sonarr.root_folder")
        if not root or root!=sonarr_root:
            raise SonarrReview()
        return SonarrOptions(configuration.value("sonarr.base_url"),sonarr_root,
                             configuration.value("sonarr.quality_profile_name"),
                             configuration.value("sonarr.timeout_seconds"),key)
    if not row["origin"] or not row["root"] or not row["profile"] or not row["timeout"]:
        raise SonarrReview()
    return SonarrOptions(row["origin"],row["root"],row["profile"],row["timeout"],key)


def _missing_episode(client,sonarr_id,identity):
    episodes,files=client.inventory(sonarr_id)
    if not isinstance(episodes,list) or not isinstance(files,list):
        raise SonarrReview()
    matched=[e for e in episodes if isinstance(e,dict)
             and e.get("seasonNumber")==identity["tvdb_season"]
             and e.get("episodeNumber")==identity["tvdb_episode"]]
    if len(matched)!=1 or type(matched[0].get("id")) is not int or matched[0]["id"]<=0:
        raise SonarrReview()
    ep=matched[0]
    if ep.get("tvdbId") is not None and ep["tvdbId"]!=identity["tvdb_episode_id"]:
        raise SonarrReview()
    if (type(ep.get("episodeFileId")) is int and ep["episodeFileId"]>0) or ep.get("hasFile") is True:
        # Do not replace someone else's existing episode file.
        raise SonarrReview()


def registration(secrets):
    async def execute(context):
        actions=ManagementActions(context.configuration.value("storage.database_path"))
        journal=KeepJournal(actions.queue.database)
        try:
            await blocking(actions.bind,context.claim,"KEEP")
            record=await blocking(journal.load,context.claim)
        except (ActionUnavailable,KeepReview,ValueError,TypeError):
            return Outcome("review","KEEP_FILE_REVIEW")

        if record["phase"]=="VERIFIED":
            if type(record["evidence"]) is not dict:
                return Outcome("review","KEEP_FILE_REVIEW")
            return Outcome(value=record["evidence"])
        if record["phase"]=="IMPORT_INTENT":
            # A previous attempt may already have submitted this command. Never
            # replay a POST from the durable uncertain boundary.
            return Outcome("review","KEEP_COMMAND_UNCERTAIN")
        try:
            key=await blocking(secrets.sonarr_api_key)
            options=_options(record,context.configuration,key)
            client=SonarrClient(options)
        except (SecretStorageError,SonarrReview):
            return Outcome("blocked","SONARR_CONFIGURATION_INVALID")

        try:
            if record["phase"]=="APPROVED":
                # Recheck actual bytes and pinned staging inode after human review.
                await blocking(staged,record,context.cancelled)
                await blocking(journal.begin_series,context.claim,context.configuration)
                record=await blocking(journal.load,context.claim)

            if record["phase"]=="SERIES_INTENT":
                # Missing-series creation is reconciled by the verified TVDB ID;
                # an uncertain create response stops for review, not blind replay.
                series_id,_=await blocking(client.ensure_series,record["approval"]["identity"]["tvdb_series_id"])
                await blocking(journal.series_ready,context.claim,series_id)
                record=await blocking(journal.load,context.claim)

            if record["phase"]=="SERIES_READY":
                proof=await blocking(staged,record,context.cancelled)
                identity=record["approval"]["identity"]
                await blocking(_missing_episode,client,record["sonarr_id"],identity)
                selected=await blocking(client.manual_import_preview,record["sonarr_id"],[{
                    "path":proof["path"],"season":identity["tvdb_season"],
                    "episode":identity["tvdb_episode"],"tvdb_episode_id":identity["tvdb_episode_id"]}])
                # Persist the exact copy request BEFORE any irreversible POST.
                await blocking(journal.import_intent,context.claim,selected)
                try:
                    command_id=await blocking(client.submit_copy,selected)
                except (SonarrUnavailable,SonarrReview):
                    return Outcome("review","KEEP_COMMAND_UNCERTAIN")
                await blocking(journal.accepted,context.claim,command_id)
                record=await blocking(journal.load,context.claim)

            if record["phase"]=="COMMAND_ACCEPTED":
                status=await blocking(client.command_status,record["command_id"])
                if status in ("queued","started"):
                    return Outcome("defer","KEEP_IMPORT_PENDING",delay_ms=30000)
                if status!="completed":
                    return Outcome("review","SONARR_IMPORT_REVIEW")
                proof=await blocking(staged,record,context.cancelled)
                result=await blocking(verified_library,record,client,context.cancelled,proof)
                # Only worker finish may commit VERIFIED and jobs.DONE together.
                return Outcome(value=result)

            return Outcome("review","KEEP_FILE_REVIEW")
        except SonarrUnavailable:
            # Safe reads can be retried manually. An uncertain series creation
            # must never cause an unexamined repeated Sonarr POST.
            return Outcome("review","SONARR_UNAVAILABLE")
        except (SonarrReview,KeepReview,KeepFileReview):
            return Outcome("review","SONARR_IMPORT_REVIEW")
        except OSError:
            return Outcome("retry","SONARR_UNAVAILABLE")
    return Registration(KIND,DEFINITION,execute,persist=_persist)
