"""Durable Keep request boundary; media promotion is not implemented yet.

Never report completion or move/delete files without a verified staging source,
publication journal and the permanent-library contract. This registration makes
that missing prerequisite visible instead of silently dropping operator intent.
"""
from src.nextgen.async_io import blocking
from src.nextgen.handlers import HandlerDefinition
from src.nextgen.job_contracts import Outcome, Registration
from src.nextgen.storage.management_actions import ManagementActions, ActionUnavailable

KIND='KEEP_MEDIA'
DEFINITION=HandlerDefinition(KIND,'Keep staged video in the permanent library')


def registration():
    async def execute(context):
        actions=ManagementActions(context.configuration.value('storage.database_path'))
        try:await blocking(actions.bind,context.claim,'KEEP')
        except (ActionUnavailable,ValueError,TypeError):return Outcome('review','JOB_PAYLOAD_INVALID')
        return Outcome('blocked','KEEP_NOT_READY')
    return Registration(KIND,DEFINITION,execute)
